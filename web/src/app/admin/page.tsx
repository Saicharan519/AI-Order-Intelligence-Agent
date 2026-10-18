import type { Metadata } from "next";
import { AdminPage } from "@/components/admin-page";

export const metadata: Metadata = { title: "Admin · Order Intelligence" };

export default function Admin() {
  return <AdminPage />;
}
