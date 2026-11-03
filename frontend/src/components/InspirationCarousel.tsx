import { useEffect, useRef, useState } from "react";

const SLIDE_INTERVAL_MS = 3000;
const SLIDE_TRANSITION_MS = 550;
const SWIPE_DISTANCE_PX = 50;
const SLIDES = [
  { file: "mcdonald-box-lego.png", alt: "A brick-built takeaway box filled with golden nuggets and chicken pieces" },
  { file: "boxing-glove-lego.png", alt: "A white brick-built boxing glove with gold decorative details" },
  { file: "house-lego.png", alt: "A detailed brick-built house with a blue roof, garden, and red garage door" },
];
// End copies let both directions cross the boundary by moving just one slide.
const LOOP_SLIDES = [...SLIDES.slice(-1), ...SLIDES, ...SLIDES.slice(0, 1)];

export function InspirationCarousel() {
  const [position, setPosition] = useState(1);
  const [isResetting, setIsResetting] = useState(false);
  const activeIndex = (position - 1 + SLIDES.length) % SLIDES.length;
  const [isDragging, setIsDragging] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [dragOffset, setDragOffset] = useState(0);
  const pointerStart = useRef<{ id: number; x: number; y: number } | null>(null);
  const [reducedMotion, setReducedMotion] = useState(true);

  function advanceSlide(direction: number) {
    if (isResetting) return;
    setPosition((current) => {
      if (reducedMotion) return ((current - 1 + direction + SLIDES.length) % SLIDES.length) + 1;
      if (current === 0 || current === SLIDES.length + 1) return current;
      return current + direction;
    });
  }

  useEffect(() => {
    if (position !== 0 && position !== SLIDES.length + 1) return;
    const timer = window.setTimeout(() => {
      setIsResetting(true);
      setPosition(position === 0 ? SLIDES.length : 1);
    }, reducedMotion ? 0 : SLIDE_TRANSITION_MS);
    return () => window.clearTimeout(timer);
  }, [position, reducedMotion]);

  useEffect(() => {
    if (!isResetting) return;
    // Paint the identical real slide without animation before accepting another move.
    let secondFrame = 0;
    const firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => setIsResetting(false));
    });
    return () => {
      cancelAnimationFrame(firstFrame);
      cancelAnimationFrame(secondFrame);
    };
  }, [isResetting]);

  useEffect(() => {
    const preference = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!preference) return;
    const updatePreference = () => setReducedMotion(preference.matches);
    updatePreference();
    preference.addEventListener("change", updatePreference);
    return () => preference.removeEventListener("change", updatePreference);
  }, []);

  useEffect(() => {
    if (isDragging || isFocused || reducedMotion) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) setPosition((current) => current + 1);
    }, SLIDE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [activeIndex, isDragging, isFocused, reducedMotion]);

  function cancelDrag() {
    pointerStart.current = null;
    setIsDragging(false);
    setDragOffset(0);
  }

  return (
    <div className="inspiration" role="region" aria-label="LEGO inspiration slideshow" aria-roledescription="carousel">
      <div
        className={`inspiration__viewport${isDragging ? " inspiration__viewport--dragging" : ""}`}
        tabIndex={0}
        aria-label="Drag to change image, or use the left and right arrow keys"
        onFocus={() => setIsFocused(true)}
        onBlur={() => setIsFocused(false)}
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          event.preventDefault();
          const direction = event.key === "ArrowRight" ? 1 : -1;
          advanceSlide(direction);
        }}
        onPointerDown={(event) => {
          if (event.button !== 0 || event.isPrimary === false || pointerStart.current || isResetting || position === 0 || position === SLIDES.length + 1) return;
          if (event.pointerType === "mouse") event.preventDefault();
          pointerStart.current = { id: event.pointerId, x: event.clientX, y: event.clientY };
          event.currentTarget.setPointerCapture(event.pointerId);
          setIsDragging(true);
        }}
        onPointerMove={(event) => {
          if (pointerStart.current?.id !== event.pointerId) return;
          setDragOffset(event.clientX - pointerStart.current.x);
        }}
        onPointerUp={(event) => {
          const start = pointerStart.current;
          if (!start || start.id !== event.pointerId) return;
          const distance = event.clientX - start.x;
          if (Math.abs(distance) >= SWIPE_DISTANCE_PX && Math.abs(distance) > Math.abs(event.clientY - start.y)) {
            advanceSlide(distance < 0 ? 1 : -1);
          }
          cancelDrag();
        }}
        onPointerCancel={cancelDrag}
        onLostPointerCapture={cancelDrag}
      >
        <div className="inspiration__track" style={{ transform: `translateX(calc(-${position * 100}% + ${dragOffset}px))`, transitionDuration: `${SLIDE_TRANSITION_MS}ms`, transitionProperty: isResetting || isDragging || reducedMotion ? "none" : "transform" }} aria-live="off">
          {LOOP_SLIDES.map((slide, index) => (
            <div className="inspiration__slide" key={`${slide.file}-${index}`} aria-hidden={index !== position} role="group" aria-roledescription="slide" aria-label={`${(index - 1 + SLIDES.length) % SLIDES.length + 1} of ${SLIDES.length}`}>
              <img src={`/inspiration/${slide.file}`} alt={slide.alt} loading="lazy" decoding="async" draggable={false} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
