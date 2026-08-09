/* LD_PRELOAD shim for labwc (wlroots): five jobs, all compositor-only.
 *
 * 1. Seat name — report the STREAMING seat instead of seatd's hardcoded
 *    "seat0". wlroots passes libseat_seat_name() to
 *    libinput_udev_assign_seat(), which filters devices by their udev ID_SEAT
 *    property. The host udev rule puts Sunshine's virtual devices on "seat9";
 *    with this shim labwc enumerates exactly those and never touches the
 *    desktop's real keyboard/mouse (input isolation in both directions).
 *
 * 2. Blank cursor — no-op the wlroots cursor-image setters so the dead pointer
 *    Sunshine creates isn't burned into the capture (see below).
 *
 * 3. Flat pointer acceleration (PS_POINTER_ACCEL=flat): client mouse counts
 *    arrive raw; libinput's adaptive accel on top is far too fast. Hook the
 *    device-attach, force the flat (1:1) profile on pointers.
 *
 * 4. Fake udev monitor: in a rootless user namespace the kernel does NOT
 *    deliver udev netlink uevents, so libinput's hotplug monitor never sees
 *    the devices Sunshine creates mid-session. Enumerate still works (the
 *    udev DB is visible via the bind-mounted /run/udev), so we fake ONLY the
 *    monitor: an inotify watch on /dev/input drives an eventfd, and
 *    udev_monitor_receive_device() resolves each new eventN to a REAL
 *    udev_device via the visible DB. Gated by PS_FAKE_UDEV (the host runtime
 *    always sets it); without the env the real netlink monitor is untouched.
 *    This is what lets the container run rootless: the sole reason it needed
 *    root was uevent delivery.
 *
 * 5. Cursor idle-hide (only with PS_SHOW_CURSOR, since the cursor is blanked
 *    entirely otherwise): gamescope delegates cursor drawing to the outer
 *    compositor and never clears the image when it hides its own, so labwc
 *    keeps rendering the last arrow into the capture. The shim remembers the
 *    image, tracks pointer motion and clears it after PS_CURSOR_IDLE_MS
 *    (default 3000, matching gamescope). Details at that section below.
 *
 * Logging: hotplug and delivery each print one line to stderr, on purpose and
 * ungated. They fire per device event rather than continuously, and they are
 * the only signal that a device was seen but never attached, which is the
 * failure this file exists to prevent.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/inotify.h>
#include <time.h>
#include <unistd.h>

const char *libseat_seat_name(void *seat) {
    (void)seat;
    const char *name = getenv("PS_SEAT_NAME");
    return (name && name[0]) ? name : "seat9";
}

/* ---- fake udev monitor -------------------------------------------------- */

static int fake_udev_enabled(void) {
    const char *v = getenv("PS_FAKE_UDEV");
    return v && v[0] && v[0] != '0';
}

#define FU_INPUT_DIR "/dev/input"
#define FU_MAXQ 128

static void *fu_real(const char *name) { return dlsym(RTLD_NEXT, name); }

static struct {
    void *monitor;            /* the one monitor we fake: the "input" one */
    int inotify_fd;
    int event_fd;             /* handed to libinput; EFD_SEMAPHORE, 1 per dev */
    pthread_t thread;
    pthread_mutex_t lock;
    char *queue[FU_MAXQ];     /* pending sysnames ("event27") */
    int qhead, qtail;
    void *added[FU_MAXQ];     /* devices we returned as "add" (ring) */
    int added_idx;
} FU = { .inotify_fd = -1, .event_fd = -1, .lock = PTHREAD_MUTEX_INITIALIZER };

/* Fake ONLY the monitor that filters for the "input" subsystem (libinput's).
 * wlroots' session creates a SECOND udev monitor for DRM hotplug, and faking
 * every monitor hands both the same eventfd: every new-device token then wakes
 * two consumers, and whichever reads first pops the queue. An input device
 * that lands on the session monitor is checked against DRM, unref'd and lost
 * for good, which under Sunshine's device burst at session start costs the
 * absolute mouse and the pen their attachment to labwc. */
int udev_monitor_filter_add_match_subsystem_devtype(void *monitor,
                                                    const char *subsystem,
                                                    const char *devtype) {
    int (*real)(void *, const char *, const char *) =
        fu_real("udev_monitor_filter_add_match_subsystem_devtype");
    if (fake_udev_enabled() && subsystem && strcmp(subsystem, "input") == 0) {
        pthread_mutex_lock(&FU.lock);
        FU.monitor = monitor;
        pthread_mutex_unlock(&FU.lock);
    }
    return real ? real(monitor, subsystem, devtype) : 0;
}

static int fu_is_input_monitor(void *monitor) {
    pthread_mutex_lock(&FU.lock);
    int r = FU.monitor && FU.monitor == monitor;
    pthread_mutex_unlock(&FU.lock);
    return r;
}

static void fu_push(const char *name) {
    pthread_mutex_lock(&FU.lock);
    int next = (FU.qtail + 1) % FU_MAXQ;
    int ok = next != FU.qhead;
    if (ok) { FU.queue[FU.qtail] = strdup(name); FU.qtail = next; }
    pthread_mutex_unlock(&FU.lock);
    if (ok) { uint64_t one = 1; ssize_t w = write(FU.event_fd, &one, sizeof one); (void)w; }
}

static char *fu_pop(void) {
    pthread_mutex_lock(&FU.lock);
    char *r = NULL;
    if (FU.qhead != FU.qtail) { r = FU.queue[FU.qhead]; FU.qhead = (FU.qhead + 1) % FU_MAXQ; }
    pthread_mutex_unlock(&FU.lock);
    return r;
}

/* Watch /dev/input; queue one token per newly created eventN node. Removals
 * aren't synthesized; libinput drops a device itself once its evdev fd errors
 * out (ENODEV) after the node disappears. */
static void *fu_thread(void *arg) {
    (void)arg;
    char buf[4096];
    for (;;) {
        ssize_t n = read(FU.inotify_fd, buf, sizeof buf);
        if (n <= 0) { if (n < 0 && errno == EINTR) continue; break; }
        for (char *p = buf; p < buf + n; ) {
            struct inotify_event *e = (struct inotify_event *)p;
            if (e->len && (e->mask & IN_CREATE) && strncmp(e->name, "event", 5) == 0) {
                fprintf(stderr, "[seat-shim] hotplug %s\n", e->name);
                fu_push(e->name);
            }
            p += sizeof(struct inotify_event) + e->len;
        }
    }
    return NULL;
}

/* libinput calls this once and polls the returned fd. Return an eventfd that
 * carries one readable token per pending device (EFD_SEMAPHORE), fed by the
 * inotify thread: correct level-triggered semantics regardless of how
 * libinput loops receive_device(). Non-input monitors (wlroots' DRM session
 * monitor) keep their real netlink fd, which simply stays silent rootless. */
int udev_monitor_get_fd(void *monitor) {
    int (*real)(void *) = fu_real("udev_monitor_get_fd");
    if (!fake_udev_enabled() || !fu_is_input_monitor(monitor))
        return real(monitor);
    pthread_mutex_lock(&FU.lock);
    if (FU.event_fd < 0) {
        FU.event_fd = eventfd(0, EFD_SEMAPHORE | EFD_CLOEXEC | EFD_NONBLOCK);
        FU.inotify_fd = inotify_init1(IN_CLOEXEC);
        if (FU.inotify_fd >= 0)
            inotify_add_watch(FU.inotify_fd, FU_INPUT_DIR, IN_CREATE);
        pthread_create(&FU.thread, NULL, fu_thread, NULL);
    }
    pthread_mutex_unlock(&FU.lock);
    return FU.event_fd;
}

void *udev_monitor_receive_device(void *monitor) {
    void *(*real)(void *) = fu_real("udev_monitor_receive_device");
    if (!fake_udev_enabled() || !fu_is_input_monitor(monitor))
        return real(monitor);

    uint64_t tok;
    if (read(FU.event_fd, &tok, sizeof tok) != sizeof tok)  /* consume one token */
        return NULL;
    char *name = fu_pop();
    if (!name)
        return NULL;

    void *(*get_udev)(void *) = fu_real("udev_monitor_get_udev");
    void *(*new_ss)(void *, const char *, const char *) =
        fu_real("udev_device_new_from_subsystem_sysname");
    const char *(*getprop)(void *, const char *) = fu_real("udev_device_get_property_value");
    void (*unref)(void *) = fu_real("udev_device_unref");
    void *udev = get_udev(monitor);

    /* The host udevd may not have written /run/udev/data (ID_SEAT) by the
     * time inotify fires; retry briefly until the seat property is populated.
     * After the budget the device is delivered ANYWAY: a NULL here would lose
     * the hotplug forever, and libinput filters foreign seats itself. */
    void *dev = NULL;
    int seated = 0;
    for (int i = 0; i < 50; i++) {
        void *d = new_ss(udev, "input", name);
        if (d) {
            if (getprop(d, "ID_SEAT")) { dev = d; seated = 1; break; }
            if (dev) unref(dev);
            dev = d;                       /* exists, DB not ready yet */
        }
        usleep(10000);
    }
    fprintf(stderr, "[seat-shim] deliver %s%s\n", name,
            dev ? (seated ? "" : " (no ID_SEAT yet)") : " FAILED: no udev device");
    free(name);
    if (!dev)
        return NULL;

    pthread_mutex_lock(&FU.lock);
    FU.added[FU.added_idx] = dev;                 /* tag so get_action → "add" */
    FU.added_idx = (FU.added_idx + 1) % FU_MAXQ;
    pthread_mutex_unlock(&FU.lock);
    return dev;
}

/* Devices from udev_device_new_from_subsystem_sysname carry no action string;
 * libinput needs "add" to treat a monitor device as a hotplug. Report it for
 * the devices we synthesized; everything else (incl. enumerate) passes through. */
const char *udev_device_get_action(void *dev) {
    const char *(*real)(void *) = fu_real("udev_device_get_action");
    if (fake_udev_enabled()) {
        pthread_mutex_lock(&FU.lock);
        for (int i = 0; i < FU_MAXQ; i++) {
            if (FU.added[i] == dev) { pthread_mutex_unlock(&FU.lock); return "add"; }
        }
        pthread_mutex_unlock(&FU.lock);
    }
    return real ? real(dev) : NULL;
}

/* Also blank labwc's cursor: Sunshine creates its virtual pointer devices even
 * with mouse = disabled (only the injection is gated), so labwc gains a
 * pointer capability and renders a cursor that the wlr-screencopy capture
 * overlays into the stream — a permanent dead cursor now that pointer input
 * is cut. No-op every wlroots cursor-image setter (labwc's own xcursor and
 * client-set cursors alike) so the cursor never has an image; position
 * tracking is unaffected. PS_SHOW_CURSOR=1 forwards to the real wlroots
 * symbols instead (for pointer-input experiments with PS_MOUSE_INPUT). */
static int show_cursor(void) {
    const char *v = getenv("PS_SHOW_CURSOR");
    return v && v[0] && v[0] != '0';
}

/* ---- cursor idle-hide ----------------------------------------------------
 * gamescope hides its own cursor after idle (-C 3000), but in the nested
 * setup it DELEGATES cursor drawing to the outer compositor via
 * wl_pointer.set_cursor and never clears that image on its internal hide:
 * labwc keeps rendering the last arrow forever, burned into the stream.
 * Verified by comparing the wlr capture (arrow persists) against gamescope's
 * own screenshot (no cursor) after idle. So the shim hides it: remember the
 * last cursor image the compositor set, track pointer activity in
 * wlr_cursor_move/warp_absolute, clear the image once idle (piggybacked on
 * wl_display_flush_clients, which runs on the compositor thread), and replay
 * the remembered image on the next motion. PS_CURSOR_IDLE_MS overrides the
 * timeout (default 3000, matching gamescope; 0 disables). Only active with
 * PS_SHOW_CURSOR, the cursor is blanked entirely otherwise. */
enum { CUR_NONE, CUR_XCURSOR, CUR_BUFFER, CUR_SURFACE };
static struct {
    void *cursor;             /* labwc's wlr_cursor */
    int kind;                 /* last image set: CUR_* */
    void *a;                  /* manager / buffer / surface */
    char name[64];            /* xcursor name */
    int32_t hx, hy;
    float scale;
    uint64_t last_activity_ms;
    int hidden;
} CI;

static uint64_t ci_now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + (uint64_t)(ts.tv_nsec / 1000000);
}

static uint64_t ci_timeout_ms(void) {
    const char *v = getenv("PS_CURSOR_IDLE_MS");
    if (!v || !v[0])
        return 3000;
    return (uint64_t)strtoul(v, NULL, 10);
}

static void ci_replay(void) {
    if (CI.kind == CUR_XCURSOR) {
        void (*real)(void *, void *, const char *) = fu_real("wlr_cursor_set_xcursor");
        if (real) real(CI.cursor, CI.a, CI.name);
    } else if (CI.kind == CUR_BUFFER) {
        void (*real)(void *, void *, int32_t, int32_t, float) = fu_real("wlr_cursor_set_buffer");
        if (real) real(CI.cursor, CI.a, CI.hx, CI.hy, CI.scale);
    } else if (CI.kind == CUR_SURFACE) {
        void (*real)(void *, void *, int32_t, int32_t) = fu_real("wlr_cursor_set_surface");
        if (real) real(CI.cursor, CI.a, CI.hx, CI.hy);
    }
    CI.hidden = 0;
}

static void ci_activity(void *cur) {
    if (cur)
        CI.cursor = cur;
    CI.last_activity_ms = ci_now_ms();
    if (CI.hidden)
        ci_replay();
}

void wlr_cursor_move(void *cur, void *dev, double dx, double dy) {
    void (*real)(void *, void *, double, double) = fu_real("wlr_cursor_move");
    if (show_cursor())
        ci_activity(cur);
    if (real) real(cur, dev, dx, dy);
}

void wlr_cursor_warp_absolute(void *cur, void *dev, double x, double y) {
    void (*real)(void *, void *, double, double) = fu_real("wlr_cursor_warp_absolute");
    if (show_cursor())
        ci_activity(cur);
    if (real) real(cur, dev, x, y);
}

/* Runs every compositor event-loop turn (clients keep the loop busy), so it
 * doubles as the idle timer without touching wlroots from a foreign thread. */
void wl_display_flush_clients(void *display) {
    void (*real)(void *) = fu_real("wl_display_flush_clients");
    uint64_t timeout = ci_timeout_ms();
    if (show_cursor() && timeout && !CI.hidden && CI.cursor
            && CI.kind != CUR_NONE
            && ci_now_ms() - CI.last_activity_ms > timeout) {
        void (*set_buf)(void *, void *, int32_t, int32_t, float) =
            fu_real("wlr_cursor_set_buffer");
        if (set_buf) {
            set_buf(CI.cursor, NULL, 0, 0, 1.0f);  /* NULL buffer = no image */
            CI.hidden = 1;
        }
    }
    if (real) real(display);
}

void wlr_cursor_set_xcursor(void *cur, void *manager, const char *name) {
    if (show_cursor()) {
        void (*real)(void *, void *, const char *) = dlsym(RTLD_NEXT, "wlr_cursor_set_xcursor");
        CI.cursor = cur; CI.kind = CUR_XCURSOR; CI.a = manager;
        snprintf(CI.name, sizeof CI.name, "%s", name ? name : "");
        CI.hidden = 0;
        if (real) real(cur, manager, name);
    }
}
void wlr_cursor_set_buffer(void *cur, void *buffer, int32_t hx, int32_t hy, float scale) {
    if (show_cursor()) {
        void (*real)(void *, void *, int32_t, int32_t, float) = dlsym(RTLD_NEXT, "wlr_cursor_set_buffer");
        CI.cursor = cur; CI.kind = buffer ? CUR_BUFFER : CUR_NONE; CI.a = buffer;
        CI.hx = hx; CI.hy = hy; CI.scale = scale;
        CI.hidden = 0;
        if (real) real(cur, buffer, hx, hy, scale);
    }
}
void wlr_cursor_set_surface(void *cur, void *surface, int32_t hx, int32_t hy) {
    if (show_cursor()) {
        void (*real)(void *, void *, int32_t, int32_t) = dlsym(RTLD_NEXT, "wlr_cursor_set_surface");
        CI.cursor = cur; CI.kind = surface ? CUR_SURFACE : CUR_NONE; CI.a = surface;
        CI.hx = hx; CI.hy = hy;
        CI.hidden = 0;
        if (real) real(cur, surface, hx, hy);
    }
}

/* ---- flat pointer acceleration ------------------------------------------ */

/* labwc attaches every new input device to its wlr_cursor; that is the one
 * spot where the underlying libinput device is reachable. All symbols come
 * from labwc's own wlroots/libinput via RTLD_NEXT; no link-time deps.
 * libinput enum value: LIBINPUT_CONFIG_ACCEL_PROFILE_FLAT = (1 << 0). */
void wlr_cursor_attach_input_device(void *cur, void *dev) {
    void (*real)(void *, void *) = dlsym(RTLD_NEXT, "wlr_cursor_attach_input_device");
    if (!real) return;
    real(cur, dev);

    const char *mode = getenv("PS_POINTER_ACCEL");
    if (!mode || strcmp(mode, "flat") != 0) return;
    int (*is_libinput)(void *) = dlsym(RTLD_NEXT, "wlr_input_device_is_libinput");
    void *(*handle)(void *) = dlsym(RTLD_NEXT, "wlr_libinput_get_device_handle");
    int (*avail)(void *) = dlsym(RTLD_NEXT, "libinput_device_config_accel_is_available");
    int (*set_profile)(void *, int) = dlsym(RTLD_NEXT, "libinput_device_config_accel_set_profile");
    int (*set_speed)(void *, double) = dlsym(RTLD_NEXT, "libinput_device_config_accel_set_speed");
    if (!is_libinput || !handle || !avail || !set_profile || !set_speed) return;
    if (!is_libinput(dev)) return;
    void *li = handle(dev);
    if (li && avail(li)) {
        set_profile(li, 1 /* LIBINPUT_CONFIG_ACCEL_PROFILE_FLAT */);
        set_speed(li, 0.0);
    }
}
