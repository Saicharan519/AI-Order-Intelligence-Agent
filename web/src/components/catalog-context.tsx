// The data catalog, shared with components deep in the answer tree (charts mark the months
// the data only partly covers). Loaded once by the workspace from GET /v1/catalog.
"use client";

import { createContext, useContext } from "react";
import type { Catalog } from "@/lib/types";

const CatalogContext = createContext<Catalog | null>(null);

export const CatalogProvider = CatalogContext.Provider;

export function usePartialMonths(): Set<string> {
  const catalog = useContext(CatalogContext);
  return new Set((catalog?.facts.partial_months ?? []).map((p) => p.month));
}
