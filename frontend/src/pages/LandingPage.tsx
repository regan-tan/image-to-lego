import { Link } from "react-router-dom";
import { InspirationCarousel } from "../components/InspirationCarousel";

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
        </div>
        <div className="landing__art-panel"><BrickCat /></div>
      </section>

      <section className="landing__process" id="how-it-works" aria-labelledby="process-title">
        <p className="landing__eyebrow">How it works</p>
        <div className="landing__process-heading">
          <h2 id="process-title">Three steps to<br />something amazing.</h2>
        </div>
        <ol className="landing__steps">
          <li>
            <div className="landing__step-art landing__step-art--photo" aria-hidden="true">
              <span className="landing__step-number">01</span>
              <svg viewBox="0 0 240 150" fill="none" focusable="false">
                <rect x="69" y="25" width="112" height="100" rx="10" fill="#e0d6a3" transform="rotate(9 125 75)" />
                <g transform="rotate(-8 120 75)" stroke="#252822" strokeWidth="3" strokeLinejoin="round">
                  <rect x="58" y="22" width="116" height="108" rx="9" fill="#fffefa" />
                  <rect x="68" y="32" width="96" height="72" rx="4" fill="#ffe27b" />
                  <circle cx="92" cy="52" r="9" fill="#fffefa" />
                  <path d="m68 93 28-27 19 18 20-24 29 33v11H68Z" fill="#7e9570" />
                  <path d="M96 117h40" strokeLinecap="round" />
                </g>
                <path d="M193 49V31m-9 9h18" stroke="#252822" strokeWidth="3" strokeLinecap="round" />
              </svg>
            </div>
            <div className="landing__step-copy">
              <p className="landing__step-label">Upload</p>
              <h3>Start with a photo.</h3>
              <p>Pick one object you love. A clear photo is all you need to get started.</p>
            </div>
          </li>
          <li>
            <div className="landing__step-art landing__step-art--model" aria-hidden="true">
              <span className="landing__step-number">02</span>
              <svg viewBox="0 0 240 150" fill="none" focusable="false">
                <ellipse cx="123" cy="125" rx="64" ry="10" fill="#11120f" />
                <g stroke="#ffe27b" strokeWidth="3" strokeLinejoin="round">
                  <path d="m120 21 53 30-53 31-53-31Z" fill="#535343" />
                  <path d="M67 51v58l53 30V82Z" fill="#34372e" />
                  <path d="M120 82v57l53-30V51Z" fill="#77714c" />
                  <path d="m94 36 53 31v57m0-88L94 67v57M67 80l53 30 53-30" strokeWidth="1.5" opacity=".6" />
                </g>
                <path d="M192 31v20m-10-10h20M43 88v12m-6-6h12" stroke="#ffe27b" strokeWidth="3" strokeLinecap="round" />
              </svg>
            </div>
            <div className="landing__step-copy">
              <p className="landing__step-label">Reconstruct</p>
              <h3>A whole new dimension.</h3>
              <p>Let AI turn your image into an approximate 3D model. Rotate it and take a look.</p>
            </div>
          </li>
          <li>
            <div className="landing__step-art landing__step-art--bricks" aria-hidden="true">
              <span className="landing__step-number">03</span>
              <svg viewBox="0 0 240 150" fill="none" focusable="false">
                <g stroke="#252822" strokeWidth="3" strokeLinejoin="round">
                  <path d="m61 93 60-26 61 26-60 27Z" fill="#fffefa" />
                  <path d="M61 93v25l61 26v-24Z" fill="#e5e5d9" />
                  <path d="M122 120v24l60-26V93Z" fill="#bfc2b3" />
                  <path d="m61 53 60-26 61 26-60 27Z" fill="#ffe785" />
                  <path d="M61 53v25l61 26V80Z" fill="#ffd744" />
                  <path d="M122 80v24l60-26V53Z" fill="#d8ae25" />
                  <path d="M91 44v9c0 8 24 8 24 0v-9m14 0v9c0 8 24 8 24 0v-9" fill="#ffd744" />
                  <ellipse cx="103" cy="44" rx="12" ry="5" fill="#fff0a5" />
                  <ellipse cx="141" cy="44" rx="12" ry="5" fill="#fff0a5" />
                </g>
              </svg>
            </div>
            <div className="landing__step-copy">
              <p className="landing__step-label">Build</p>
              <h3>Bring on the bricks.</h3>
              <p>Explore your LEGO-style model, find your pieces, and follow the build guide.</p>
            </div>
          </li>
        </ol>
      </section>

      <InspirationCarousel />

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
