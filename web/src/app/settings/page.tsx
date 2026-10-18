import type { Metadata } from "next";
import { SettingsPage } from "@/components/settings-page";

export const metadata: Metadata = { title: "Account settings · Order Intelligence" };

export default function Settings() {
  return <SettingsPage />;
}
