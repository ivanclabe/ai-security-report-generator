export function reportFilename(title: string | null | undefined, version: number, format?: string) {
  const extension = format === "pdf" ? "pdf" : "docx";
  return `${title || "informe-de-seguridad"}-v${version}.${extension}`.replace(/\s+/g, "-");
}
