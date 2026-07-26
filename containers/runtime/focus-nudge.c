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
// Trigger: gamescope publishes GAMESCOPE_FOCUSED_APP on its Xwayland root. Every
// game exit shows up as that property switching back to Steam's 769. A launch
// that never opens a window (cancelled, or failed between Steam and the game)
// loses the navigation too but leaves both the focused app and window alone;
// there the trace is GAMESCOPECTRL_BASELAYER_APPID, Steam's focus-control stack,
// which gains the appid on launch and loses it again on the abort. Session start
// shows up in neither, because the display is identified by the very same
// property,
// so its first observed value is already the final one — that case is nudged on
// attach instead. Three shots per trigger (500 ms, 2.5 s, 10 s), because Steam
// moves its focused window around for a while and the UI settles late. Since the
// state is invisible, this is deliberately blind: a nudge that was not needed
// re-focuses the same window and changes nothing. All shots stay inside the
// first ten seconds, so none can interrupt someone typing in Steam's search.
//
// Env: PS_FOCUS_NUDGE=disabled turns it off, PS_FOCUS_NUDGE_DELAYS overrides the
//      millisecond offsets (default "500,2500,10000"), PS_FOCUS_NUDGE_WAIT_S
//      bounds the wait for gamescope's display — unbounded by default, since
//      with dynamic resolution gamescope only starts on the first client.

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

// The focus-control stack Steam publishes, as a comparable string ("" when
// unset). Steam pushes an appid here while a launch is in flight and pops it
// again when the game exits or the launch is aborted.
static void baselayer_stack(Display *dpy, Window root, Atom atom,
                            char *out, size_t out_len)
{
    out[0] = '\0';
    Atom type;
    int format;
    unsigned long items, after;
    unsigned char *data = NULL;
    if (XGetWindowProperty(dpy, root, atom, 0, 16, False, XA_CARDINAL, &type,
                           &format, &items, &after, &data) != Success)
        return;
    if (data == NULL)
        return;
    if (type == XA_CARDINAL && format == 32) {
        size_t used = 0;
        for (unsigned long i = 0; i < items && used + 24 < out_len; i++)
            used += (size_t)snprintf(out + used, out_len - used, "%lu,",
                                     ((unsigned long *)data)[i]);
    }
    XFree(data);
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

// Each offset is measured from the trigger; nudge() itself costs 250 ms, which
// is accounted for so the offsets stay honest. The later shots matter because
// Steam moves its focused window around in the first seconds.
static void run_nudges(Display *dpy, Window root, Atom app_atom,
                       const long *delays, size_t count)
{
    long waited = 0;
    for (size_t i = 0; i < count; i++) {
        if (delays[i] > waited)
            sleep_ms(delays[i] - waited);
        waited = (delays[i] > waited ? delays[i] : waited) + 250;
        // A launch can succeed while the sequence is still running. Dropping
        // the focus into a starting game would look like alt-tab to it, so the
        // remaining shots are abandoned as soon as Steam is no longer focused.
        if (focused_app(dpy, root, app_atom) != (long)STEAM_APPID) {
            logf_nudge("focus left Steam — dropping the remaining nudges");
            return;
        }
        nudge(dpy);
    }
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
        if (wait_s > 0 && elapsed >= wait_s)
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

static int env_int(const char *name, int fallback)
{
    const char *value = getenv(name);
    if (value == NULL || !*value)
        return fallback;
    char *end = NULL;
    long parsed = strtol(value, &end, 10);
    if (end == value || parsed <= 0 || parsed > 86400)
        return fallback;
    return (int)parsed;
}

int main(void)
{
    const char *off = getenv("PS_FOCUS_NUDGE");
    if (off != NULL && strcmp(off, "disabled") == 0)
        return 0;

    long delays[MAX_DELAYS] = { 500, 2500, 10000 };
    size_t delay_count = 3;
    const char *spec = getenv("PS_FOCUS_NUDGE_DELAYS");
    if (spec != NULL && *spec) {
        size_t parsed = parse_delays(spec, delays, MAX_DELAYS);
        if (parsed > 0)
            delay_count = parsed;
    }

    Atom atom = None;
    Window root = None;
    Display *dpy = open_gamescope_display(&atom, &root, env_int("PS_FOCUS_NUDGE_WAIT_S", 0));
    char stack[256] = "", previous_stack[256] = "";
    if (dpy == NULL) {
        logf_nudge("no gamescope X display appeared — not watching");
        return 3;
    }
    Atom stack_atom = XInternAtom(dpy, "GAMESCOPECTRL_BASELAYER_APPID", False);
    XSelectInput(dpy, root, PropertyChangeMask);
    long previous = focused_app(dpy, root, atom);
    baselayer_stack(dpy, root, stack_atom, previous_stack, sizeof(previous_stack));

    // The display is found BY that property, so at startup its value is already
    // the final one and there is no switch left to observe — the session-start
    // case has to be nudged here or never.
    if (previous == (long)STEAM_APPID) {
        logf_nudge("Steam already holds the focus at startup");
        run_nudges(dpy, root, atom, delays, delay_count);
    }

    for (;;) {
        XEvent ev;
        XNextEvent(dpy, &ev);  // blocks; the process idles between switches
        if (ev.type != PropertyNotify)
            continue;
        if (ev.xproperty.atom == atom) {
            long current = focused_app(dpy, root, atom);
            if (current == previous)
                continue;
            // Steam took the focus back: a game just exited.
            if (current == (long)STEAM_APPID) {
                logf_nudge("focus switched %ld -> %ld", previous, current);
                run_nudges(dpy, root, atom, delays, delay_count);
            }
            previous = current;
        } else if (ev.xproperty.atom == stack_atom) {
            // A launch that never produces a window (cancelled, or failed
            // between Steam and the game) loses the navigation just the same,
            // and leaves the focused app and window untouched — the pushed and
            // popped appid on this stack is the only trace of it.
            baselayer_stack(dpy, root, stack_atom, stack, sizeof(stack));
            if (strcmp(stack, previous_stack) == 0)
                continue;
            snprintf(previous_stack, sizeof(previous_stack), "%s", stack);
            if (focused_app(dpy, root, atom) == (long)STEAM_APPID) {
                logf_nudge("launch stack changed to [%s]", stack);
                run_nudges(dpy, root, atom, delays, delay_count);
            }
        }
    }
}
