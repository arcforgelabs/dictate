import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement these; the UI calls them harmlessly.
if (!window.matchMedia) {
  window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
}
if (!global.requestAnimationFrame) {
  global.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
  global.cancelAnimationFrame = (id) => clearTimeout(id);
}
if (window.HTMLCanvasElement && !window.HTMLCanvasElement.prototype.getContext.__dictateMocked) {
  const canvasContext = {
    save() {},
    restore() {},
    scale() {},
    clearRect() {},
    beginPath() {},
    moveTo() {},
    arcTo() {},
    closePath() {},
    fill() {},
  };
  window.HTMLCanvasElement.prototype.getContext = function getContext(type) {
    return type === "2d" ? canvasContext : null;
  };
  window.HTMLCanvasElement.prototype.getContext.__dictateMocked = true;
}
