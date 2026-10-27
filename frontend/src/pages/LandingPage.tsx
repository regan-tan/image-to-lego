import { Link } from "react-router-dom";

interface LandingPageProps {
  isAuthenticated: boolean;
}

function BrickCat() {
  return (
    <div className="brick-cat" aria-hidden="true">
      <div className="brick-cat__scan" />
      <svg viewBox="0 0 520 560" focusable="false">
        <g className="brick-cat__shadow">
          <ellipse cx="265" cy="495" rx="150" ry="21" />
        </g>
        <g className="brick-cat__body">
          <path d="M132 278h256v171H132z" className="cat-fill" />
          <path d="M155 252h211v30H155zM105 326h45v76h-45zM371 315h45v87h-45z" className="cat-fill" />
          <path d="M380 315c56-6 68-47 35-73" className="cat-stroke" />
          <path d="M162 279h203M132 331h255M132 389h255M204 279v170M302 279v170" className="cat-line" />
          <circle cx="171" cy="300" r="13" className="cat-stud" />
          <circle cx="239" cy="300" r="13" className="cat-stud" />
          <circle cx="307" cy="300" r="13" className="cat-stud" />
          <circle cx="348" cy="354" r="13" className="cat-stud" />
          <circle cx="239" cy="409" r="13" className="cat-stud" />
          <circle cx="307" cy="409" r="13" className="cat-stud" />
        </g>
        <g className="brick-cat__head">
          <path d="M131 123l67 29h136l64-29v191H131z" className="cat-fill" />
          <path d="M131 123l50 65-50 33zM398 123l-50 65 50 33z" className="cat-accent" />
          <path d="M131 221h267M165 152v161M364 152v161" className="cat-line" />
          <g className="brick-cat__eyes">
            <rect x="190" y="205" width="48" height="29" rx="4" className="cat-eye" />
            <rect x="292" y="205" width="48" height="29" rx="4" className="cat-eye" />
          </g>
          <path d="M252 245h14l7 9-14 10-14-10zM225 278c18 16 52 16 70 0" className="cat-stroke" />
          <circle cx="189" cy="176" r="12" className="cat-stud" />
          <circle cx="259" cy="176" r="12" className="cat-stud" />
          <circle cx="329" cy="176" r="12" className="cat-stud" />
        </g>
      </svg>
      <span className="brick-cat__tag brick-cat__tag--top">UNIT 01 / FELINE</span>
      <span className="brick-cat__tag brick-cat__tag--bottom">SCANNING FORM</span>
      <span className="brick-cat__corner brick-cat__corner--one" />
      <span className="brick-cat__corner brick-cat__corner--two" />
    </div>
  );
}

export function LandingPage({ isAuthenticated }: LandingPageProps) {
  const workspacePath = "/workspace";
  const loginPath = `/login?next=${encodeURIComponent(workspacePath)}`;
  const destination = isAuthenticated ? workspacePath : loginPath;

  return (
    <main className="landing">
      <header className="landing__header">
        <Link to="/" className="landing__brand" aria-label="Image to LEGO home">
          <span className="landing__brand-mark" aria-hidden="true">IL</span>
          <span>IMAGE TO LEGO</span>
        </Link>
        <nav className="landing__nav" aria-label="Main navigation">
          <a href="#how-it-works">How it works</a>
          <a href="#about">About</a>
          <Link className="landing__nav-action" to={destination}>
            {isAuthenticated ? "Open workspace" : "Sign in"}
          </Link>
        </nav>
      </header>
      <section className="landing__hero" aria-labelledby="landing-title">
        <div className="landing__grid" aria-hidden="true" />
        <div className="landing__hero-copy">
          <p className="landing__eyebrow"><span /> AI RECONSTRUCTION LAB / 2026</p>
          <h1 id="landing-title">FROM<br />PIXELS<br />TO BRICKS<span>.</span></h1>
          <p className="landing__description">Turn your favourite images into stunning 3D LEGO-inspired creations, powered by AI.</p>
          <div className="landing__actions">
            <Link className="landing__button landing__button--primary" to={destination}>
              {isAuthenticated ? "OPEN WORKSPACE" : "GET STARTED"}
              <span aria-hidden="true">↗</span>
            </Link>
            <a className="landing__button landing__button--ghost" href="#how-it-works">HOW IT WORKS</a>
          </div>
        </div>
        <BrickCat />
        <p className="landing__scroll-note">SCROLL TO EXPLORE <span>↓</span></p>
        <p className="landing__index">01 / 03</p>
      </section>
      <section className="landing__process" id="how-it-works" aria-labelledby="process-title">
        <div className="landing__section-intro"><p className="landing__eyebrow"><span /> THE PROCESS</p><h2 id="process-title">MAKE A NEW<br />KIND OF MODEL.</h2></div>
        <ol className="landing__steps"><li><span>01</span><h3>UPLOAD</h3><p>Start a private project with a JPEG, PNG, or WebP image.</p></li><li><span>02</span><h3>RECONSTRUCT</h3><p>Choose to generate a 3D model from your ready image.</p></li><li><span>03</span><h3>BUILD</h3><p>Explore the resulting brick model, parts list, and build guide.</p></li></ol>
      </section>
      <section className="landing__about" id="about" aria-labelledby="about-title"><p className="landing__eyebrow"><span /> ABOUT THE SYSTEM</p><div><h2 id="about-title">YOUR IMAGE,<br />REIMAGINED IN BRICKS.</h2><p>Image to LEGO pairs an AI reconstruction workflow with a deterministic brick conversion, so you can inspect a LEGO-inspired interpretation of an image in one workspace.</p></div></section>
      <section className="landing__closing" aria-labelledby="closing-title"><p className="landing__eyebrow"><span /> YOUR TURN</p><h2 id="closing-title">READY TO BUILD?</h2><Link className="landing__button landing__button--primary" to={destination}>START CREATING <span aria-hidden="true">↗</span></Link></section>
      <footer className="landing__footer"><span>IMAGE TO LEGO / CAPSTONE PROJECT</span><span>MADE FOR CURIOUS BUILDERS</span></footer>
    </main>
  );
}
