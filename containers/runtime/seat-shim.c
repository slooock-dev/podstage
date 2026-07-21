/* LD_PRELOAD shim for cage (wlroots): three jobs, all cage-only.
 *
 * 1. Seat name — report the STREAMING seat instead of seatd's hardcoded
 *    "seat0". wlroots passes libseat_seat_name() to
 *    libinput_udev_assign_seat(), which filters devices by their udev ID_SEAT
 *    property. The host udev rule puts Sunshine's virtual devices on "seat9";
 *    with this shim cage enumerates exactly those and never touches the
 *    desktop's real keyboard/mouse (input isolation in both directions).
 *
 * 2. Blank cursor — no-op the wlroots cursor-image setters so the dead pointer
 *    Sunshine creates isn't burned into the capture (see below).
 *
 * 3. Fake udev monitor — in a rootless user namespace the kernel does NOT
 *    deliver udev netlink uevents, so libinput's hotplug monitor never sees
 *    the devices Sunshine creates mid-session. Enumerate still works (the
 *    udev DB is visible via the bind-mounted /run/udev), so we fake ONLY the
 *    monitor: an inotify watch on /dev/input drives an eventfd, and
 *    udev_monitor_receive_device() resolves each new eventN to a REAL
 *    udev_device via the visible DB. Gated by PS_FAKE_UDEV (the host runtime
 *    always sets it); without the env the real netlink monitor is untouched.
 *    This is what lets the container run rootless — the sole reason it needed
 *    root was uevent delivery.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/inotify.h>
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

static struct {
    void *monitor;            /* libinput's real monitor (for udev context) */
    int inotify_fd;
    int event_fd;             /* handed to libinput; EFD_SEMAPHORE, 1 per dev */
    pthread_t thread;
    pthread_mutex_t lock;
    char *queue[FU_MAXQ];     /* pending sysnames ("event27") */
    int qhead, qtail;
    void *added[FU_MAXQ];     /* devices we returned as "add" (ring) */
    int added_idx;
} FU = { .inotify_fd = -1, .event_fd = -1, .lock = PTHREAD_MUTEX_INITIALIZER };

static void *fu_real(const char *name) { return dlsym(RTLD_NEXT, name); }

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
 * aren't synthesized — libinput drops a device itself once its evdev fd errors
 * out (ENODEV) after the node disappears. */
static void *fu_thread(void *arg) {
    (void)arg;
    char buf[4096];
    for (;;) {
        ssize_t n = read(FU.inotify_fd, buf, sizeof buf);
        if (n <= 0) { if (n < 0 && errno == EINTR) continue; break; }
        for (char *p = buf; p < buf + n; ) {
            struct inotify_event *e = (struct inotify_event *)p;
            if (e->len && (e->mask & IN_CREATE) && strncmp(e->name, "event", 5) == 0)
                fu_push(e->name);
            p += sizeof(struct inotify_event) + e->len;
        }
    }
    return NULL;
}

/* libinput calls this once and polls the returned fd. Return an eventfd that
 * carries one readable token per pending device (EFD_SEMAPHORE), fed by the
 * inotify thread — correct level-triggered semantics regardless of how
 * libinput loops receive_device(). */
int udev_monitor_get_fd(void *monitor) {
    int (*real)(void *) = fu_real("udev_monitor_get_fd");
    if (!fake_udev_enabled())
        return real(monitor);
    pthread_mutex_lock(&FU.lock);
    if (FU.event_fd < 0) {
        FU.monitor = monitor;
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
    if (!fake_udev_enabled())
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

    /* The host udevd may not have written /run/udev/data (ID_SEAT) by the time
     * inotify fires — retry briefly until the seat property is populated. */
    void *dev = NULL;
    for (int i = 0; i < 50; i++) {
        dev = new_ss(udev, "input", name);
        if (dev) {
            if (getprop(dev, "ID_SEAT"))
                break;
            unref(dev);
            dev = NULL;
        }
        usleep(10000);
    }
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

/* Also blank cage's cursor: Sunshine creates its virtual pointer devices even
 * with mouse = disabled (only the injection is gated), so cage gains a
 * pointer capability and renders a cursor that the wlr-screencopy capture
 * overlays into the stream — a permanent dead cursor now that pointer input
 * is cut. No-op every wlroots cursor-image setter (cage's own xcursor and
 * client-set cursors alike) so the cursor never has an image; position
 * tracking is unaffected. PS_SHOW_CURSOR=1 forwards to the real wlroots
 * symbols instead (for pointer-input experiments with PS_MOUSE_INPUT). */
static int show_cursor(void) {
    const char *v = getenv("PS_SHOW_CURSOR");
    return v && v[0] && v[0] != '0';
}

void wlr_cursor_set_xcursor(void *cur, void *manager, const char *name) {
    if (show_cursor()) {
        void (*real)(void *, void *, const char *) = dlsym(RTLD_NEXT, "wlr_cursor_set_xcursor");
        if (real) real(cur, manager, name);
    }
}
void wlr_cursor_set_buffer(void *cur, void *buffer, int32_t hx, int32_t hy, float scale) {
    if (show_cursor()) {
        void (*real)(void *, void *, int32_t, int32_t, float) = dlsym(RTLD_NEXT, "wlr_cursor_set_buffer");
        if (real) real(cur, buffer, hx, hy, scale);
    }
}
void wlr_cursor_set_surface(void *cur, void *surface, int32_t hx, int32_t hy) {
    if (show_cursor()) {
        void (*real)(void *, void *, int32_t, int32_t) = dlsym(RTLD_NEXT, "wlr_cursor_set_surface");
        if (real) real(cur, surface, hx, hy);
    }
}
