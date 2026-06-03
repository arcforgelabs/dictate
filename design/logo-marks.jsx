// logo-marks.jsx — six Dictate logo directions, each 2–3 solid geometries.
// All draw in currentColor on a 0 0 120 120 grid so they invert cleanly.
// <Mark kind size uid /> — uid salts mask ids so repeated instances don't collide.

// Cradle (02·c) geometry is tweakable — provided via context so every instance
// (hero, tray, favicon, lockup) updates together.
const CradleCtx = React.createContext({ R:20, armH:12, slot:13 });
window.CradleCtx = CradleCtx;

function Mark({ kind, size, uid }){
  const cradle = React.useContext(CradleCtx);
  const dim = size ? { width:size, height:size } : null;
  const common = { viewBox:"0 0 120 120", style:dim||undefined, fill:"currentColor", xmlns:"http://www.w3.org/2000/svg" };

  switch(kind){
    // 01 · Caret — cursor bar + voice dot (a custom 'i')
    case "caret":
      return (
        <svg {...common}>
          <circle cx="60" cy="24" r="15"/>
          <rect x="47" y="44" width="26" height="66" rx="13"/>
        </svg>
      );

    // 02 · Capsule — mic capsule resting on a baseline
    case "capsule":
      return (
        <svg {...common}>
          <rect x="40" y="13" width="40" height="74" rx="20"/>
          <rect x="31" y="97" width="58" height="13" rx="6.5"/>
        </svg>
      );

    // 03 · Waveform — three rounded bars
    case "wave":
      return (
        <svg {...common}>
          <rect x="19" y="40" width="18" height="40" rx="9"/>
          <rect x="51" y="18" width="18" height="84" rx="9"/>
          <rect x="83" y="31" width="18" height="58" rx="9"/>
        </svg>
      );

    // ---- 02 · Capsule riffs ----------------------------------------
    // Desk mic: capsule + stem + foot
    case "cap-stem":
      return (
        <svg {...common}>
          <rect x="46" y="12" width="28" height="58" rx="14"/>
          <rect x="57" y="70" width="6" height="22" rx="3"/>
          <rect x="42" y="92" width="36" height="12" rx="6"/>
        </svg>
      );
    // Mic resting in a cradle arc — tweakable: arm height, slot depth, arc radius.
    // arcCy = vertical center of the U arc; capsule bottom edge sits at y=64.
    case "cap-cradle": {
      const R = cradle.R, armH = cradle.armH, slot = cradle.slot;
      const arcCy = 64 - slot;
      const left = 60 - R, right = 60 + R, top = arcCy - armH;
      const d = `M${left} ${top} L${left} ${arcCy} A${R} ${R} 0 0 0 ${right} ${arcCy} L${right} ${top}`;
      return (
        <svg {...common}>
          <rect x="47" y="16" width="26" height="48" rx="13"/>
          <path d={d} fill="none" stroke="currentColor" strokeWidth="8" strokeLinecap="round"/>
        </svg>
      );
    }
    // Capsule with grille slots + foot
    case "cap-grille": {
      const m="cg-"+(uid||"x");
      return (
        <svg {...common}>
          <defs><mask id={m}>
            <rect x="0" y="0" width="120" height="120" fill="#fff"/>
            <rect x="51" y="38" width="18" height="5" rx="2.5" fill="#000"/>
            <rect x="51" y="50" width="18" height="5" rx="2.5" fill="#000"/>
          </mask></defs>
          <rect x="42" y="13" width="36" height="72" rx="18" mask={`url(#${m})`}/>
          <rect x="33" y="96" width="54" height="12" rx="6"/>
        </svg>
      );
    }
    // Mic floating in a listening halo
    case "cap-ring":
      return (
        <svg {...common}>
          <circle cx="60" cy="60" r="45" fill="none" stroke="currentColor" strokeWidth="9"/>
          <rect x="49" y="33" width="22" height="46" rx="11"/>
        </svg>
      );

    // ---- 03 · Waveform riffs ---------------------------------------
    // Symmetric five-bar
    case "wave5":
      return (
        <svg {...common}>
          <rect x="12" y="46" width="12" height="28" rx="6"/>
          <rect x="33" y="32" width="12" height="56" rx="6"/>
          <rect x="54" y="18" width="12" height="84" rx="6"/>
          <rect x="75" y="32" width="12" height="56" rx="6"/>
          <rect x="96" y="46" width="12" height="28" rx="6"/>
        </svg>
      );
    // Minimal two-bar
    case "wave-min":
      return (
        <svg {...common}>
          <rect x="42" y="38" width="16" height="44" rx="8"/>
          <rect x="62" y="22" width="16" height="76" rx="8"/>
        </svg>
      );
    // Waveform inside a ring
    case "wave-orb":
      return (
        <svg {...common}>
          <circle cx="60" cy="60" r="46" fill="none" stroke="currentColor" strokeWidth="9"/>
          <rect x="37" y="48" width="10" height="24" rx="5"/>
          <rect x="55" y="40" width="10" height="40" rx="5"/>
          <rect x="73" y="46" width="10" height="28" rx="5"/>
        </svg>
      );
    // Equalizer of dots
    case "wave-dots":
      return (
        <svg {...common}>
          <circle cx="30" cy="72" r="6.5"/><circle cx="30" cy="52" r="6.5"/>
          <circle cx="60" cy="78" r="6.5"/><circle cx="60" cy="58" r="6.5"/><circle cx="60" cy="38" r="6.5"/><circle cx="60" cy="18" r="6.5"/>
          <circle cx="90" cy="72" r="6.5"/><circle cx="90" cy="52" r="6.5"/><circle cx="90" cy="32" r="6.5"/>
        </svg>
      );

    // ---- Unconstrained — richer marks ------------------------------
    // Voiceprint: a full audio-clip waveform
    case "vp": {
      const cx=[12.5,22,31.5,41,50.5,60,69.5,79,88.5,98,107.5];
      const h =[16,30,52,70,56,84,56,70,52,30,16];
      return (
        <svg {...common}>
          {cx.map((x,i)=>(
            <rect key={i} x={x-3} y={60-h[i]/2} width="6" height={h[i]} rx="3"/>
          ))}
        </svg>
      );
    }
    // Studio mic, fully drawn
    case "mic-studio": {
      const m="ms-"+(uid||"x");
      return (
        <svg {...common}>
          <defs><mask id={m}>
            <rect x="0" y="0" width="120" height="120" fill="#fff"/>
            <rect x="52" y="25" width="16" height="4" rx="2" fill="#000"/>
            <rect x="52" y="37" width="16" height="4" rx="2" fill="#000"/>
            <rect x="52" y="49" width="16" height="4" rx="2" fill="#000"/>
          </mask></defs>
          <rect x="44" y="9" width="32" height="58" rx="16" mask={`url(#${m})`}/>
          <path d="M32 56 A28 28 0 0 0 88 56" fill="none" stroke="currentColor" strokeWidth="8" strokeLinecap="round"/>
          <rect x="57" y="78" width="6" height="20" rx="3"/>
          <rect x="44" y="98" width="32" height="11" rx="5.5"/>
        </svg>
      );
    }
    // Radial waveform — the orb as a sun-burst equalizer
    case "wave-radial": {
      const lens=[46,38,44,40,46,38,44,40,46,38,44,40];
      const inner=20;
      const lines=lens.map((L,i)=>{
        const a=i*30*Math.PI/180;
        return {
          x1:60+inner*Math.cos(a), y1:60+inner*Math.sin(a),
          x2:60+L*Math.cos(a),     y2:60+L*Math.sin(a)
        };
      });
      return (
        <svg {...common}>
          {lines.map((l,i)=>(
            <line key={i} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} stroke="currentColor" strokeWidth="7" strokeLinecap="round"/>
          ))}
          <circle cx="60" cy="60" r="7"/>
        </svg>
      );
    }
    // Speech-to-text: rising sound resolving into a cursor + voice dot
    case "s2t":
      return (
        <svg {...common}>
          <rect x="13" y="46" width="14" height="28" rx="7"/>
          <rect x="33" y="38" width="14" height="44" rx="7"/>
          <rect x="53" y="30" width="14" height="60" rx="7"/>
          <circle cx="88" cy="16" r="9"/>
          <rect x="79" y="32" width="18" height="64" rx="9"/>
        </svg>
      );
    // Monogram D — the bowl wraps a mic-capsule stem
    case "mono-d": {
      const m="md-"+(uid||"x");
      return (
        <svg {...common}>
          <defs><mask id={m}>
            <rect x="0" y="0" width="120" height="120" fill="#fff"/>
            <rect x="36" y="34" width="10" height="4" rx="2" fill="#000"/>
            <rect x="36" y="46" width="10" height="4" rx="2" fill="#000"/>
          </mask></defs>
          <rect x="32" y="14" width="18" height="92" rx="9" mask={`url(#${m})`}/>
          <path d="M41 14 A46 46 0 0 1 41 106" fill="none" stroke="currentColor" strokeWidth="18" strokeLinecap="round"/>
        </svg>
      );
    }
    // Pulse, layered — the breathing orb with broken sound rings
    case "pulse-layered":
      return (
        <svg {...common}>
          <circle cx="60" cy="60" r="45" fill="none" stroke="currentColor" strokeWidth="6.5" strokeLinecap="round" strokeDasharray="5 13"/>
          <circle cx="60" cy="60" r="26" fill="none" stroke="currentColor" strokeWidth="8"/>
          <circle cx="60" cy="60" r="10"/>
        </svg>
      );

    // ---- u3 · Radial wave — variations -----------------------------
    // Fine burst — 24 thin spokes
    case "wr-fine": {
      const N=24, inner=22;
      return (
        <svg {...common}>
          {Array.from({length:N},(_,i)=>{
            const a=i*(360/N)*Math.PI/180, L=(i%2?41:46);
            return <line key={i} x1={60+inner*Math.cos(a)} y1={60+inner*Math.sin(a)} x2={60+L*Math.cos(a)} y2={60+L*Math.sin(a)} stroke="currentColor" strokeWidth="3.6" strokeLinecap="round"/>;
          })}
          <circle cx="60" cy="60" r="5"/>
        </svg>
      );
    }
    // Ring + rays — bars radiating from a solid listening ring
    case "wr-ring": {
      const N=16, inner=28, lens=[44,36,40,46,38,42,36,44,40,36,46,38,42,40,36,44];
      return (
        <svg {...common}>
          <circle cx="60" cy="60" r="23" fill="none" stroke="currentColor" strokeWidth="7"/>
          {lens.map((L,i)=>{
            const a=i*(360/N)*Math.PI/180;
            return <line key={i} x1={60+inner*Math.cos(a)} y1={60+inner*Math.sin(a)} x2={60+L*Math.cos(a)} y2={60+L*Math.sin(a)} stroke="currentColor" strokeWidth="6" strokeLinecap="round"/>;
          })}
        </svg>
      );
    }
    // Circular voiceprint — a waveform envelope wrapped into a circle
    case "wr-voice": {
      const N=30, inner=16;
      return (
        <svg {...common}>
          {Array.from({length:N},(_,i)=>{
            const a=i*(360/N)*Math.PI/180;
            const L=inner+12+12*(0.5+0.5*Math.sin(i/N*Math.PI*2*4));
            return <line key={i} x1={60+inner*Math.cos(a)} y1={60+inner*Math.sin(a)} x2={60+L*Math.cos(a)} y2={60+L*Math.sin(a)} stroke="currentColor" strokeWidth="3.4" strokeLinecap="round"/>;
          })}
          <circle cx="60" cy="60" r="4.5"/>
        </svg>
      );
    }
    // Grille — spokes pointing inward to a core
    case "wr-inward": {
      const N=22, outer=45;
      return (
        <svg {...common}>
          {Array.from({length:N},(_,i)=>{
            const a=i*(360/N)*Math.PI/180;
            const innr=26+6*Math.sin(i/N*Math.PI*2*5);
            return <line key={i} x1={60+outer*Math.cos(a)} y1={60+outer*Math.sin(a)} x2={60+innr*Math.cos(a)} y2={60+innr*Math.sin(a)} stroke="currentColor" strokeWidth="4" strokeLinecap="round"/>;
          })}
          <circle cx="60" cy="60" r="7"/>
        </svg>
      );
    }
    // Pulse burst — core dot, ring, and short outer ticks
    case "wr-pulse": {
      const N=12;
      return (
        <svg {...common}>
          {Array.from({length:N},(_,i)=>{
            const a=i*30*Math.PI/180;
            return <line key={i} x1={60+34*Math.cos(a)} y1={60+34*Math.sin(a)} x2={60+44*Math.cos(a)} y2={60+44*Math.sin(a)} stroke="currentColor" strokeWidth="6" strokeLinecap="round"/>;
          })}
          <circle cx="60" cy="60" r="24" fill="none" stroke="currentColor" strokeWidth="7"/>
          <circle cx="60" cy="60" r="9"/>
        </svg>
      );
    }

    // 04 · Pulse — dot inside a ring (the breath)
    case "pulse":
      return (
        <svg {...common}>
          <circle cx="60" cy="60" r="44" fill="none" stroke="currentColor" strokeWidth="13"/>
          <circle cx="60" cy="60" r="15"/>
        </svg>
      );

    // 05 · Aside — solid speech form with a tail
    case "speech":
      return (
        <svg {...common}>
          <rect x="17" y="20" width="86" height="64" rx="22"/>
          <path d="M41 82 L41 110 L68 83 Z"/>
        </svg>
      );

    // 06 · Aperture — listening orb with a vertical slot cut through
    case "aperture": {
      const m = "ap-"+(uid||"x");
      return (
        <svg {...common}>
          <defs>
            <mask id={m}>
              <rect x="0" y="0" width="120" height="120" fill="#fff"/>
              <rect x="53" y="33" width="14" height="54" rx="7" fill="#000"/>
            </mask>
          </defs>
          <circle cx="60" cy="60" r="46" mask={`url(#${m})`}/>
        </svg>
      );
    }

    default:
      return null;
  }
}
window.Mark = Mark;
