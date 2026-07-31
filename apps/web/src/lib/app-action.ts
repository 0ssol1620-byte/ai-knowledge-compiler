export const APP_ACTION_HREFS = {
  home: "/quick-convert",
  projects: "/projects",
  jobs: "/activity",
  "knowledge-bases": "/knowledge-bases",
  benchmarks: "/analytics",
  recipes: "/settings",
  exports: "/workspace",
  api: "/api-workflows",
  usage: "/usage",
  billing: "/settings",
} as const;

export function appActionHref(route: string): string {
  if (route.startsWith("projects/") && route.endsWith("/exports")) {
    return "/workspace";
  }
  if (route.startsWith("projects/")) return "/quick-convert";
  if (route.startsWith("settings/")) return "/settings";
  if (route.startsWith("admin/")) return "/admin";
  if (route.startsWith("document/")) return "/workspace";

  const top = route.split("/")[0] ?? "home";
  return APP_ACTION_HREFS[top as keyof typeof APP_ACTION_HREFS] ?? "/home";
}
