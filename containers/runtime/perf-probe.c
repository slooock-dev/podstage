// podstage perf probe — per-app frametimes from gamescope, for the host GUI.
//
// gamescope hands out the presented frametime of each app over its private
// `gamescope_control` protocol (`request_app_performance_stats` → event
// `app_performance_stats`, v6, PERF_QUERY feature) — the same number Steam's
// overlay and mangoapp show. Compositor-side, so it reads identically on
// NVIDIA, AMD and Intel, unlike any encoder counter. Three gamescope details:
//
//   * The events only fire while the `mangoapp_use_output_timing` ConVar is 0;
//     gamescope 3.16 defaults it to 1 and then never calls
//     wlserver_app_presented(). The entrypoint flips it via gamescopectl.
//   * A request is one-shot (next present of that appid, then dropped), so
//     re-arming on every event IS the sample pump — no timer polling.
//   * Stats are keyed by Steam AppID: read from the running reaper's
//     `SteamLaunch AppId=` (as core/monitor.py does, and as gamescope itself
//     tags the window), with Steam's 769 armed alongside so the menu keeps
//     reporting while a game boots.
//
// The current fps (averaged over the last second) lands as JSON in PS_PERF_FILE
// (a tmpfs the host shares in, /run/podstage) for the host GUI, written by
// rename() so no reader sees a half file. An idle window is written as
// `samples: 0`, which distinguishes "nothing rendering" from "probe gone"
// (file mtime).
//
// Env: PS_PERF_FILE (default $HOME/.cache/podstage/perf.json),
//      PS_PERF_INTERVAL_MS (default 1000), PS_PERF_WAIT_S (default 180: how
//      long to wait for gamescope's socket), GAMESCOPE_WAYLAND_DISPLAY (else
//      the gamescope-* socket is auto-found).

#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <wayland-client.h>

#include "gamescope-control-client-protocol.h"

#define STEAM_APPID       769u   // Steam's own windows (Big Picture / menu)
#define RING              512u   // frametime samples kept (2 s at 240 fps)
#define FPS_WINDOW_NS     1000000000ull  // averaging window behind the fps
#define GAME_FRESH_NS     1500000000ull  // game slot preferred while this new
#define SLOT_GAME         0
#define SLOT_STEAM        1
#define SLOTS             2

__attribute__((format(printf, 1, 2)))
static void logf_probe(const char *fmt, ...)
{
    va_list args;
    fputs("[podstage-perf] ", stderr);
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);
    fputc('\n', stderr);
    fflush(stderr);
}

static uint64_t now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

// -- sample rings ------------------------------------------------------------

struct slot {
    uint32_t app_id;
    bool pending;             // a request is armed and still unanswered
    uint64_t last_sample_ns;
    uint64_t frametime[RING];
    uint64_t stamp[RING];
    size_t pushed;            // total ever pushed; index = pushed % RING
};

static struct slot g_slots[SLOTS];
static struct gamescope_control *g_control;
static uint32_t g_perf_query_version;

static void slot_reset(struct slot *s, uint32_t app_id)
{
    memset(s, 0, sizeof(*s));
    s->app_id = app_id;
}

static void slot_push(struct slot *s, uint64_t frametime_ns, uint64_t now)
{
    s->frametime[s->pushed % RING] = frametime_ns;
    s->stamp[s->pushed % RING] = now;
    s->pushed++;
    s->last_sample_ns = now;
}

// Frametimes from the last `window_ns`, newest first. Returns the count.
static size_t slot_window(const struct slot *s, uint64_t now, uint64_t window_ns,
                          uint64_t *out, size_t max_out)
{
    size_t have = s->pushed < RING ? s->pushed : RING;
    size_t n = 0;
    for (size_t i = 0; i < have && n < max_out; i++) {
        size_t idx = (s->pushed - 1 - i) % RING;
        if (now - s->stamp[idx] > window_ns)
            break;  // older than the window — everything behind it is too
        out[n++] = s->frametime[idx];
    }
    return n;
}

// -- appid discovery ---------------------------------------------------------

// The Steam AppID currently launched in the sandbox, from the reaper's
// "SteamLaunch AppId=" argv (0 = none, i.e. Big Picture / menu).
static uint32_t detect_game_appid(void)
{
    static const char needle[] = "SteamLaunch AppId=";
    DIR *proc = opendir("/proc");
    if (!proc)
        return 0;
    uint32_t found = 0;
    struct dirent *ent;
    while (!found && (ent = readdir(proc)) != NULL) {
        if (ent->d_name[0] < '0' || ent->d_name[0] > '9')
            continue;
        char path[PATH_MAX];
        snprintf(path, sizeof(path), "/proc/%s/cmdline", ent->d_name);
        FILE *f = fopen(path, "r");
        if (!f)
            continue;
        char buf[4096];
        size_t len = fread(buf, 1, sizeof(buf) - 1, f);
        fclose(f);
        for (size_t i = 0; i < len; i++)  // argv is NUL-separated
            if (buf[i] == '\0')
                buf[i] = ' ';
        buf[len] = '\0';
        const char *hit = strstr(buf, needle);
        if (hit) {
            unsigned long id = strtoul(hit + sizeof(needle) - 1, NULL, 10);
            if (id > 0 && id < UINT32_MAX)
                found = (uint32_t)id;
        }
    }
    closedir(proc);
    return found;
}

// -- JSON output -------------------------------------------------------------

static void mkdir_parents(const char *file_path)
{
    char path[PATH_MAX];
    snprintf(path, sizeof(path), "%s", file_path);
    char *slash = strrchr(path, '/');
    if (!slash)
        return;
    *slash = '\0';
    for (char *p = path + 1; *p; p++) {
        if (*p != '/')
            continue;
        *p = '\0';
        mkdir(path, 0755);
        *p = '/';
    }
    mkdir(path, 0755);
}

static void write_json(const char *path, const struct slot *s, uint64_t now)
{
    uint64_t fps_win[RING];
    size_t n_fps = slot_window(s, now, FPS_WINDOW_NS, fps_win, RING);

    char tmp[PATH_MAX + 8];
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    FILE *f = fopen(tmp, "w");
    if (!f) {
        logf_probe("cannot write %s (%s)", tmp, strerror(errno));
        return;
    }
    fprintf(f, "{\"schema\":1,\"source\":\"gamescope_control\",\"ts\":%lld,"
               "\"app_id\":%u,\"samples\":%zu",
            (long long)time(NULL), s->app_id, n_fps);
    if (n_fps > 0) {
        uint64_t sum = 0;
        for (size_t i = 0; i < n_fps; i++)
            sum += fps_win[i];
        double avg_ns = (double)sum / (double)n_fps;
        if (avg_ns > 0)
            fprintf(f, ",\"fps\":%.1f", 1e9 / avg_ns);
    }
    fprintf(f, "}\n");
    fclose(f);
    if (rename(tmp, path) != 0)
        logf_probe("cannot rename into %s (%s)", path, strerror(errno));
}

// -- wayland glue ------------------------------------------------------------

static void on_feature_support(void *data, struct gamescope_control *control,
                               uint32_t feature, uint32_t version, uint32_t flags)
{
    (void)data; (void)control; (void)flags;
    if (feature == GAMESCOPE_CONTROL_FEATURE_PERF_QUERY)
        g_perf_query_version = version;
}

static void on_active_display_info(void *data, struct gamescope_control *control,
                                   const char *connector, const char *make,
                                   const char *model, uint32_t flags,
                                   struct wl_array *refresh_rates)
{
    (void)data; (void)control; (void)connector; (void)make; (void)model;
    (void)flags; (void)refresh_rates;  // not our business
}

static void on_screenshot_taken(void *data, struct gamescope_control *control,
                                const char *path)
{
    (void)data; (void)control; (void)path;
}

static void on_app_performance_stats(void *data, struct gamescope_control *control,
                                     uint32_t app_id, uint32_t frametime_lo,
                                     uint32_t frametime_hi)
{
    (void)data; (void)control;
    uint64_t frametime_ns = ((uint64_t)frametime_hi << 32) | frametime_lo;
    uint64_t now = now_ns();
    for (int i = 0; i < SLOTS; i++) {
        if (g_slots[i].app_id != app_id)
            continue;
        g_slots[i].pending = false;  // one-shot request consumed → re-arm
        // gamescope reports the delta between the two most recent presents;
        // absurd values (first frame after a resume, clock jumps) would wreck
        // the averages, so clamp to 1 µs … 2 s.
        if (frametime_ns >= 1000ull && frametime_ns <= 2000000000ull)
            slot_push(&g_slots[i], frametime_ns, now);
        return;
    }
}

static const struct gamescope_control_listener control_listener = {
    .feature_support = on_feature_support,
    .active_display_info = on_active_display_info,
    .screenshot_taken = on_screenshot_taken,
    .app_performance_stats = on_app_performance_stats,
};

static void on_registry_global(void *data, struct wl_registry *registry,
                               uint32_t name, const char *interface,
                               uint32_t version)
{
    (void)data;
    if (strcmp(interface, gamescope_control_interface.name) != 0)
        return;
    uint32_t bind_version = version < 6 ? version : 6;
    g_control = wl_registry_bind(registry, name, &gamescope_control_interface,
                                 bind_version);
    gamescope_control_add_listener(g_control, &control_listener, NULL);
    if (version < 6)
        logf_probe("gamescope_control v%u has no perf query (needs v6)", version);
}

static void on_registry_global_remove(void *data, struct wl_registry *registry,
                                      uint32_t name)
{
    (void)data; (void)registry; (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = on_registry_global,
    .global_remove = on_registry_global_remove,
};

// gamescope's own wayland socket is "gamescope-<slot>" in XDG_RUNTIME_DIR
// (wlserver.cpp), exported to its children as GAMESCOPE_WAYLAND_DISPLAY. This
// probe is a sibling of gamescope, not a child, so it may have to find it.
static bool find_gamescope_socket(char *out, size_t out_len)
{
    const char *env = getenv("GAMESCOPE_WAYLAND_DISPLAY");
    if (env && *env) {
        snprintf(out, out_len, "%s", env);
        return true;
    }
    const char *runtime_dir = getenv("XDG_RUNTIME_DIR");
    if (!runtime_dir || !*runtime_dir)
        return false;
    DIR *d = opendir(runtime_dir);
    if (!d)
        return false;
    bool found = false;
    struct dirent *ent;
    while (!found && (ent = readdir(d)) != NULL) {
        if (strncmp(ent->d_name, "gamescope-", 10) != 0)
            continue;
        // Skip the lock file and the libei socket next to the real one.
        size_t len = strlen(ent->d_name);
        if (len > 5 && strcmp(ent->d_name + len - 5, ".lock") == 0)
            continue;
        if (len > 3 && strcmp(ent->d_name + len - 3, "-ei") == 0)
            continue;
        snprintf(out, out_len, "%s", ent->d_name);
        found = true;
    }
    closedir(d);
    return found;
}

static struct wl_display *connect_with_wait(int wait_s)
{
    for (int elapsed = 0;; elapsed++) {
        char socket[NAME_MAX + 2];
        if (find_gamescope_socket(socket, sizeof(socket))) {
            struct wl_display *display = wl_display_connect(socket);
            if (display) {
                logf_probe("connected to %s", socket);
                return display;
            }
        }
        if (elapsed >= wait_s)
            return NULL;
        sleep(1);
    }
}

// -- main --------------------------------------------------------------------

static int env_int(const char *name, int fallback)
{
    const char *value = getenv(name);
    if (!value || !*value)
        return fallback;
    char *end = NULL;
    long parsed = strtol(value, &end, 10);
    if (end == value || parsed <= 0 || parsed > INT_MAX)
        return fallback;
    return (int)parsed;
}

int main(void)
{
    char out_path[PATH_MAX];
    const char *env_path = getenv("PS_PERF_FILE");
    if (env_path && *env_path) {
        snprintf(out_path, sizeof(out_path), "%s", env_path);
    } else {
        const char *home = getenv("HOME");
        if (!home || !*home) {
            logf_probe("neither PS_PERF_FILE nor HOME set — nothing to write");
            return 2;
        }
        snprintf(out_path, sizeof(out_path), "%s/.cache/podstage/perf.json", home);
    }
    int interval_ms = env_int("PS_PERF_INTERVAL_MS", 1000);
    int wait_s = env_int("PS_PERF_WAIT_S", 180);

    struct wl_display *display = connect_with_wait(wait_s);
    if (!display) {
        logf_probe("no gamescope wayland socket after %ds — giving up", wait_s);
        return 3;
    }
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    wl_display_roundtrip(display);  // globals
    if (!g_control) {
        logf_probe("gamescope_control not exposed — no performance metrics");
        return 3;
    }
    wl_display_roundtrip(display);  // feature_support events
    if (wl_proxy_get_version((struct wl_proxy *)g_control) < 6) {
        logf_probe("bound gamescope_control is older than v6 — no perf query");
        return 3;
    }
    if (g_perf_query_version == 0)
        logf_probe("gamescope did not advertise the perf-query feature — "
                   "trying anyway");

    mkdir_parents(out_path);
    slot_reset(&g_slots[SLOT_GAME], 0);
    slot_reset(&g_slots[SLOT_STEAM], STEAM_APPID);
    logf_probe("writing %s every %dms", out_path, interval_ms);

    uint64_t next_write = now_ns();
    uint64_t next_appid_scan = 0;
    int fd = wl_display_get_fd(display);

    for (;;) {
        uint64_t now = now_ns();

        if (now >= next_appid_scan) {
            next_appid_scan = now + 1000000000ull;
            uint32_t app_id = detect_game_appid();
            if (app_id != g_slots[SLOT_GAME].app_id)
                slot_reset(&g_slots[SLOT_GAME], app_id);  // game came or went
        }

        // Re-arm every idle slot. Requests are one-shot and answered on the
        // app's next present, so an armed-but-silent slot simply means nothing
        // is rendering for that appid.
        for (int i = 0; i < SLOTS; i++) {
            if (g_slots[i].app_id == 0 || g_slots[i].pending)
                continue;
            gamescope_control_request_app_performance_stats(g_control,
                                                            g_slots[i].app_id);
            g_slots[i].pending = true;
        }

        if (now >= next_write) {
            next_write = now + (uint64_t)interval_ms * 1000000ull;
            // Report the game while it is actually presenting, else the Steam
            // UI — mirrors what the stream shows.
            const struct slot *report = &g_slots[SLOT_STEAM];
            const struct slot *game = &g_slots[SLOT_GAME];
            if (game->app_id != 0 && game->last_sample_ns != 0 &&
                now - game->last_sample_ns <= GAME_FRESH_NS)
                report = game;
            write_json(out_path, report, now);
        }

        while (wl_display_prepare_read(display) != 0)
            wl_display_dispatch_pending(display);
        if (wl_display_flush(display) < 0 && errno != EAGAIN) {
            wl_display_cancel_read(display);
            logf_probe("gamescope connection lost — exiting");
            break;
        }
        struct pollfd pfd = { .fd = fd, .events = POLLIN };
        int timeout = (int)((next_write - now_ns()) / 1000000ull);
        int rc = poll(&pfd, 1, timeout > 0 ? (timeout < 250 ? timeout : 250) : 0);
        if (rc > 0 && (pfd.revents & POLLIN)) {
            if (wl_display_read_events(display) < 0) {
                logf_probe("gamescope connection closed — exiting");
                break;
            }
        } else {
            wl_display_cancel_read(display);
            if (rc < 0 && errno != EINTR) {
                logf_probe("poll failed (%s) — exiting", strerror(errno));
                break;
            }
        }
        if (wl_display_dispatch_pending(display) < 0) {
            logf_probe("gamescope dispatch failed — exiting");
            break;
        }
    }
    wl_display_disconnect(display);
    return 0;
}
