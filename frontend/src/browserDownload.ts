/**
 * Sends the browser to a signed download link. The link's `attachment` disposition makes the
 * browser save the file instead of leaving the page. Kept in its own module so tests can replace it.
 */
export function startBrowserDownload(url: string): void {
  window.location.assign(url);
}
