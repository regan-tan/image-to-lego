import { Link } from "react-router-dom";

interface LandingPageProps {
  isAuthenticated: boolean;
}

export function LandingPage({ isAuthenticated }: LandingPageProps) {
  const workspacePath = "/workspace";
  const destination = isAuthenticated ? workspacePath : "/login";
  const destinationState = isAuthenticated ? undefined : { returnTo: workspacePath };

  return (
    <main className="landing">
      <header className="landing__header">
        <Link to="/" className="landing__brand" aria-label="Image to LEGO home">
          <span className="landing__brand-mark" aria-hidden="true">⌃</span>
          <span><strong>image</strong> to <strong>LEGO</strong></span>
        </Link>
        <nav className="landing__nav" aria-label="Main navigation">
          <a href="#how-it-works">How it works</a>
          <a href="#about">About</a>
          <Link className="landing__nav-action" to={destination} state={destinationState}>
            {isAuthenticated ? "Open workspace" : "Get started"} ↗
          </Link>
        </nav>
      </header>

      <section className="landing__hero" aria-labelledby="landing-title">
        <div className="landing__hero-copy">
          <p className="landing__eyebrow">From image to something real</p>
          <h1 id="landing-title">Your ideas.<br />Made of<br /><span>bricks.</span></h1>
          <p className="landing__description">Turn an everyday photo into an extraordinary LEGO-inspired 3D creation. Reconstruct, customize, and build it, one brick at a time.</p>
          <div className="landing__actions">
            <Link className="landing__button landing__button--primary" to={destination} state={destinationState}>Start creating <span aria-hidden="true">↗</span></Link>
            <a className="landing__button landing__button--secondary" href="#how-it-works">See how it works <span aria-hidden="true">↘</span></a>
          </div>
          <p className="landing__journey">01 / 03 <span>Upload image</span><i /> <span>Generate model</span><i /> <span>Build</span></p>
        </div>
        <div className="landing__art-panel"><BrickCat /></div>
      </section>

      <section className="landing__process" id="how-it-works" aria-labelledby="process-title">
        <p className="landing__eyebrow">How it works</p>
        <div className="landing__process-heading">
          <h2 id="process-title">Three steps to<br />something amazing.</h2>
          <p>Simple from<br />start to finish<br />/ 001–003</p>
        </div>
        <ol className="landing__steps">
          <li><span className="landing__step-icon" aria-hidden="true">↥</span><p>01 — Upload</p><h3>Start with a photo.</h3><span>Choose a clear picture of anything that sparks your curiosity.</span></li>
          <li><span className="landing__step-icon" aria-hidden="true">◇</span><p>02 — Reconstruct</p><h3>See it in 3D.</h3><span>Generate an approximate 3D representation using AI reconstruction.</span></li>
          <li><span className="landing__step-icon" aria-hidden="true">▦</span><p>03 — Build</p><h3>Make it brick by brick.</h3><span>Explore the LEGO-style conversion, part inventory, and build guide.</span></li>
        </ol>
      </section>

      <section className="landing__closing" id="about" aria-labelledby="closing-title">
        <p className="landing__eyebrow">Let’s make something</p>
        <h2 id="closing-title">What will you build?</h2>
        <p>Your next great idea could start with just one image.</p>
        <Link className="landing__button landing__button--yellow" to={destination} state={destinationState}>Create your first project <span aria-hidden="true">↗</span></Link>
      </section>
      <footer className="landing__footer"><span>© 2026 image to LEGO</span><span>Built to explore what’s possible</span></footer>
    </main>
  );
}

function BrickCat() {
  return (
    <svg className="brick-cat" viewBox="0 0 520 560" aria-hidden="true" focusable="false">
      <ellipse cx="265" cy="500" rx="150" ry="20" className="brick-cat__shadow" />
      <path d="M132 278h256v171H132zM155 252h211v30H155zM105 326h45v76h-45zM371 315h45v87h-45z" className="brick-cat__fill" />
      <path d="M380 315c56-6 68-47 35-73M162 279h203M132 331h255M132 389h255M204 279v170M302 279v170" className="brick-cat__line" />
      <path d="M131 123l67 29h136l64-29v191H131z" className="brick-cat__fill" />
      <path d="M131 123l50 65-50 33zM398 123l-50 65 50 33z" className="brick-cat__accent" />
      <path d="M131 221h267M165 152v161M364 152v161" className="brick-cat__line" />
      <rect x="190" y="205" width="48" height="29" rx="5" className="brick-cat__eye" /><rect x="292" y="205" width="48" height="29" rx="5" className="brick-cat__eye" />
      <path d="M252 245h14l7 9-14 10-14-10zM225 278c18 16 52 16 70 0" className="brick-cat__line" />
      {[ [171,300], [239,300], [307,300], [348,354], [239,409], [307,409], [189,176], [259,176], [329,176] ].map(([cx, cy]) => <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="12" className="brick-cat__stud" />)}
    </svg>
  );
}
