import type { Metadata } from "next";
import { Suspense } from "react";
import { SignUpForm } from "@/components/auth-forms";

export const metadata: Metadata = { title: "Create your account · Order Intelligence" };

// The invite code is read from the URL in the browser (useSearchParams needs a Suspense
// boundary so the rest of the page can be prerendered).
export default function SignupPage() {
  return (
    <Suspense>
      <SignUpForm />
    </Suspense>
  );
}
