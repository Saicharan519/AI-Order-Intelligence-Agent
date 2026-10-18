import type { Metadata } from "next";
import { SignInForm } from "@/components/auth-forms";

export const metadata: Metadata = { title: "Sign in · Order Intelligence" };

export default function LoginPage() {
  return <SignInForm />;
}
