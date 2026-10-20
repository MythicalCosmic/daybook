import { Mark } from "../components/Mark";

/** Shown while the app signs in with Telegram: the design's short splash. */
export function Splash({ tagline }: { tagline: string }) {
  return (
    <div className="splash" aria-busy="true">
      <div className="splash-blob splash-blob--a" />
      <div className="splash-blob splash-blob--b" />
      <div className="splash-mark">
        <Mark size={64} animated />
        <div className="heading splash-name">Daybook</div>
      </div>
      <div className="splash-tagline">{tagline}</div>
    </div>
  );
}
