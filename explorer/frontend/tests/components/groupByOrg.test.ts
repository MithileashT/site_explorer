import { describe, it, expect } from "vitest";
import type { RIOProject } from "@/lib/types";

function groupByOrg(projects: RIOProject[]): [string, RIOProject[]][] {
  const map = new Map<string, RIOProject[]>();
  for (const p of projects) {
    const key = p.org_name || "";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(p);
  }
  return Array.from(map.entries());
}

describe("groupByOrg", () => {
  it("groups projects by org_name", () => {
    const projects: RIOProject[] = [
      { name: "jpn-tok-001", guid: "p1", organization_guid: "org-jp", org_name: "warehouse" },
      { name: "usa-chi-001", guid: "p2", organization_guid: "org-us", org_name: "Sootballs US Warehouse" },
      { name: "jpn-osa-001", guid: "p3", organization_guid: "org-jp", org_name: "warehouse" },
    ];
    const groups = groupByOrg(projects);
    expect(groups).toHaveLength(2);
    const jp = groups.find(([l]) => l === "warehouse")!;
    expect(jp[1]).toHaveLength(2);
  });

  it("uses empty string key when org_name missing", () => {
    const projects: RIOProject[] = [
      { name: "jpn-tok-001", guid: "p1", organization_guid: "org-jp" },
    ];
    const groups = groupByOrg(projects);
    expect(groups[0][0]).toBe("");
  });
});
