// TitleBar.jsx — one interior, per-OS window controls. The control cluster,
// alignment and corner radius change with `platform`; nothing else forks.
// Linux (GNOME/Adwaita + KDE/Breeze) is the focus; win/mac kept for parity.
// Stage 3: receded chrome — wordmark + "Settings" label removed; gear lives here.
import { Icon, Mark } from "../icons.jsx";
import { ipc } from "../ipc.js";

function WinCaps() {
  return (
    <div className="wincaps">
      <button title="Minimize" onClick={() => ipc.windowControl("minimize")}><Icon name="minus" size={11} /></button>
      <button title="Maximize" onClick={() => ipc.windowControl("maximize")}><Icon name="square" size={11} /></button>
      <button className="x" title="Close" onClick={() => ipc.windowControl("close")}><Icon name="x" size={11} /></button>
    </div>
  );
}

function Adwaita() {
  return (
    <div className="adw">
      <button title="Minimize" onClick={() => ipc.windowControl("minimize")}><Icon name="minus" size={11} /></button>
      <button title="Maximize" onClick={() => ipc.windowControl("maximize")}><Icon name="square" size={11} /></button>
      <button className="x" title="Close" onClick={() => ipc.windowControl("close")}><Icon name="x" size={11} /></button>
    </div>
  );
}

function Breeze() {
  return (
    <div className="breeze">
      <button title="Minimize" onClick={() => ipc.windowControl("minimize")}><Icon name="minus" size={12} /></button>
      <button title="Maximize" onClick={() => ipc.windowControl("maximize")}><Icon name="square" size={12} /></button>
      <button className="x" title="Close" onClick={() => ipc.windowControl("close")}><Icon name="x" size={12} /></button>
    </div>
  );
}

function Controls({ platform }) {
  if (platform === "win11" || platform === "win10") return <WinCaps />;
  if (platform === "kde") return <Breeze />;
  if (platform === "mac") return null; // native traffic lights live on the left
  return <Adwaita />; // gnome / linux default
}

export default function TitleBar({ platform }) {
  return (
    <div className="titlebar" data-tauri-drag-region>
      <div className="tb-left">
        {platform === "mac"
          ? <span className="lights"><i className="c" /><i className="m" /><i className="g" /></span>
          : <span className="tb-mark"><Mark size={16} /></span>}
      </div>
      <div className="tb-ctrls">
        <Controls platform={platform} />
      </div>
    </div>
  );
}
