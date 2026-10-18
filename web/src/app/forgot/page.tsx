import type { Metadata } from "next";
import { ForgotPasswordForm } from "@/components/auth-forms";

export const metadata: Metadata = { title: "Forgot password · Order Intelligence" };

export default function Forgot() {
  return <ForgotPasswordForm />;
}
