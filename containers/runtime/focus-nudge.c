// podstage focus nudge — heals Steam Big Picture's gamepad navigation.
//
// Symptom: after a game exits (and sometimes right after session start) Big
// Picture takes controller input but cannot focus its own elements — the Play
// button never highlights. Holding B until the side menu opens fixes it.
//
// Diagnosed in a live session: in the broken state gamescope's
// GAMESCOPE_FOCUSED_WINDOW, the X input focus and Steam's own STEAM_INPUT_FOCUS
// all agree and point at the Big Picture window. A dump before and after the B
// workaround is byte-for-byte identical, so nothing outside Steam is wrong and
// nothing outside Steam can detect the state — it is Steam's UI that lost its
// navigation focus. Dropping the X input focus and handing it straight back
// does heal it (verified on the broken state), which is all this does.
//
// Trigger: gamescope publishes GAMESCOPE_FOCUSED_APP on its Xwayland root.
// Whenever that becomes Steam's 769 — session start, and every game exit — the
// nudge runs twice with a short gap. Since the state is invisible, this is
// deliberately blind: a nudge that was not needed re-focuses the same window
// and changes nothing. It stays inside the first seconds after the switch so it
// can never interrupt someone typing in Steam's search field.
//
// Env: PS_FOCUS_NUDGE=disabled turns it off, PS_FOCUS_NUDGE_DELAYS overrides
//      the millisecond offsets after the switch (default "500,2500").

#define _GNU_SOURCE
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <X11/Xatom.h>
#include <X11/Xlib.h>

#define STEAM_APPID  769ul
#define MAX_DELAYS   8

__attribute__((format(printf, 1, 2)))
static void logf_nudge(const char *fmt, ...)
{
    va_list args;
    fputs("[podstage-focus] ", stderr);
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);
    fputc('\n', stderr);
    fflush(stderr);
}

static void sleep_ms(long ms)
{
    struct timespec ts = { ms / 1000, (ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
}

// The focused app id gamescope publishes, or -1 when the property is unset.
static long focused_app(Display *dpy, Window root, Atom atom)
{
    Atom type;
    int format;
    unsigned long items, after;
    unsigned char *data = NULL;
    if (XGetWindowProperty(dpy, root, atom, 0, 1, False, XA_CARDINAL, &type,
                           &format, &items, &after, &data) != Success)
        return -1;
    long value = -1;
    if (data != NULL) {
        if (type == XA_CARDINAL && format == 32 && items >= 1)
            value = (long)*(unsigned long *)data;
        XFree(data);
    }
    return value;
}

// Drop the input focus and hand it straight back to the same window. The
// focus-out/focus-in pair is what makes Steam's UI re-arm its navigation.
static void nudge(Display *dpy)
{
    Window focus = None;
    int revert = RevertToNone;
    XGetInputFocus(dpy, &focus, &revert);
    if (focus == None || focus == PointerRoot) {
        logf_nudge("no window holds the input focus — skipping");
        return;
    }
    XSetInputFocus(dpy, PointerRoot, RevertToPointerRoot, CurrentTime);
    XSync(dpy, False);
    sleep_ms(250);
    XSetInputFocus(dpy, focus, RevertToNone, CurrentTime);
    XSync(dpy, False);
    logf_nudge("nudged focus on window 0x%lx", (unsigned long)focus);
}

// gamescope's WM runs on the Xwayland display whose root carries its atoms; as
// a sibling process we have no DISPLAY, so probe the sockets it created.
static Display *open_gamescope_display(Atom *out_atom, Window *out_root,
                                       int wait_s)
{
    for (int elapsed = 0;; elapsed++) {
        for (int i = 0; i < 10; i++) {
            char name[8];
            snprintf(name, sizeof(name), ":%d", i);
            Display *dpy = XOpenDisplay(name);
            if (dpy == NULL)
                continue;
            Window root = DefaultRootWindow(dpy);
            Atom atom = XInternAtom(dpy, "GAMESCOPE_FOCUSED_APP", True);
            if (atom != None && focused_app(dpy, root, atom) >= 0) {
                logf_nudge("watching %s", name);
                *out_atom = atom;
                *out_root = root;
                return dpy;
            }
            XCloseDisplay(dpy);
        }
        if (elapsed >= wait_s)
            return NULL;
        sleep(1);
    }
}

static size_t parse_delays(const char *spec, long *out, size_t max_out)
{
    size_t n = 0;
    while (*spec && n < max_out) {
        char *end = NULL;
        long ms = strtol(spec, &end, 10);
        if (end == spec)
            break;
        if (ms >= 0 && ms <= 60000)
            out[n++] = ms;
        spec = (*end == ',') ? end + 1 : end;
    }
    return n;
}

int main(void)
{
    const char *off = getenv("PS_FOCUS_NUDGE");
    if (off != NULL && strcmp(off, "disabled") == 0)
        return 0;

    long delays[MAX_DELAYS] = { 500, 2500 };
    size_t delay_count = 2;
    const char *spec = getenv("PS_FOCUS_NUDGE_DELAYS");
    if (spec != NULL && *spec) {
        size_t parsed = parse_delays(spec, delays, MAX_DELAYS);
        if (parsed > 0)
            delay_count = parsed;
    }

    Atom atom = None;
    Window root = None;
    Display *dpy = open_gamescope_display(&atom, &root, 180);
    if (dpy == NULL) {
        logf_nudge("no gamescope X display appeared — not watching");
        return 3;
    }
    XSelectInput(dpy, root, PropertyChangeMask);
    long previous = focused_app(dpy, root, atom);

    for (;;) {
        XEvent ev;
        XNextEvent(dpy, &ev);  // blocks; the process idles between switches
        if (ev.type != PropertyNotify || ev.xproperty.atom != atom)
            continue;
        long current = focused_app(dpy, root, atom);
        if (current == previous)
            continue;
        // Steam took the focus back: session start, or a game just exited.
        if (current == (long)STEAM_APPID) {
            logf_nudge("focus switched %ld -> %ld", previous, current);
            long waited = 0;
            for (size_t i = 0; i < delay_count; i++) {
                if (delays[i] > waited)
                    sleep_ms(delays[i] - waited);
                waited = (delays[i] > waited ? delays[i] : waited) + 250;
                nudge(dpy);  // costs 250 ms itself, counted above
            }
        }
        previous = current;
    }
}
