/** Preview navigation accepts only the isolated runtime's HTTPS origin. */
export function isolatedPreviewUrl(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "https:" || !url.hostname.endsWith(".vercel.run") ||
      url.username || url.password || (url.port && url.port !== "443")) {
    throw new Error("The runtime returned an invalid isolated preview URL");
  }
  return url.href;
}
