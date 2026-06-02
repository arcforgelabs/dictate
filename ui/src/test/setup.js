import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement these; the UI calls them harmlessly.
if (!window.matchMedia) {
  window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
}
if (!global.requestAnimationFrame) {
  global.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
  global.cancelAnimationFrame = (id) => clearTimeout(id);
}
