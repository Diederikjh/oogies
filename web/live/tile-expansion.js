// Animate the existing picture; manual scrolling takes precedence over focus.
const DURATION = 360;
const SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "]);
let stopActiveScroll = null;

export class TileExpansion {
  constructor(tile, viewport, fitPicture) {
    this.tile = tile;
    this.viewport = viewport;
    this.fitPicture = fitPicture;
    this.cancel = () => {};
  }

  toggle(change) {
    // Measure the current animated rectangle before cancelling a rapid toggle.
    const before = this.tile.getBoundingClientRect();
    const beforeHeight = this.viewport.getBoundingClientRect().height;
    const beforeTop = before.top + window.scrollY;
    this.cancel();
    stopActiveScroll?.();
    change();
    this.fitPicture();
    const after = this.tile.getBoundingClientRect();
    const afterHeight = this.viewport.getBoundingClientRect().height;
    const startScroll = window.scrollY;
    const focusPosition = () => {
      const bounds = this.tile.getBoundingClientRect();
      const center = window.scrollY + bounds.top + bounds.height / 2 - window.innerHeight / 2;
      return Math.max(0, Math.min(center, document.documentElement.scrollHeight - window.innerHeight));
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      window.scrollTo({top:focusPosition(), behavior:"instant"});
      return;
    }

    const options = {duration:DURATION, easing:"cubic-bezier(.22,1,.36,1)"};
    this.tile.classList.add("is-animating");
    const animations = [
      this.tile.animate([
        {width:`${before.width}px`, transform:`translate(${before.left - after.left}px, ${beforeTop - after.top - startScroll}px)`},
        {width:`${after.width}px`, transform:"translate(0, 0)"}
      ], options),
      this.viewport.animate([{height:`${beforeHeight}px`}, {height:`${afterHeight}px`}], options)
    ];
    const events = new AbortController();
    let frame = 0;
    let finished = false;
    let scrolling = true;
    let expectedScroll = window.scrollY;
    const stopScroll = () => {
      scrolling = false;
      cancelAnimationFrame(frame);
      if (stopActiveScroll === stopScroll) stopActiveScroll = null;
    };
    const cleanup = () => {
      if (finished) return;
      finished = true;
      stopScroll();
      events.abort();
      for (const animation of animations) animation.cancel();
      this.tile.classList.remove("is-animating");
      this.fitPicture();
      this.cancel = () => {};
    };
    this.cancel = cleanup;
    stopActiveScroll = stopScroll;

    const listen = (name, handler) => window.addEventListener(name, handler,
      {capture:true, passive:true, signal:events.signal});
    listen("wheel", stopScroll);
    listen("touchstart", stopScroll);
    listen("touchmove", stopScroll);
    listen("pointerdown", stopScroll);
    listen("keydown", event => {
      if (!SCROLL_KEYS.has(event.key)) return;
      if (event.target.closest?.("input, textarea, select, [contenteditable=true]")) return;
      if (event.key === " " && event.target.closest?.("button")) return;
      stopScroll();
    });
    // Covers scrollbar dragging and scroll changes without a wheel/key event.
    // Our own instant scrolls are recognised by their actual resulting offset.
    listen("scroll", () => {
      if (Math.abs(window.scrollY - expectedScroll) > 1) stopScroll();
    });
    listen("resize", cleanup);

    const started = performance.now();
    const follow = now => {
      if (!scrolling || finished) return;
      if (!this.tile.getClientRects().length) { cleanup(); return; }
      const progress = Math.max(0, Math.min(1, (now - started) / DURATION));
      const eased = 1 - (1 - progress) ** 3;
      window.scrollTo({top:startScroll + (focusPosition() - startScroll) * eased, behavior:"instant"});
      expectedScroll = window.scrollY;
      if (progress < 1) frame = requestAnimationFrame(follow);
    };
    frame = requestAnimationFrame(follow);
    Promise.all(animations.map(animation => animation.finished)).then(cleanup, () => {});
  }

  dispose() { this.cancel(); }
}
