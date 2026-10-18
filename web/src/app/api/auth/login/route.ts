// See src/lib/server/proxy.ts: talks to the API and sets or clears the httpOnly session cookie.
import { signIn } from "@/lib/server/proxy";

export async function POST(request: Request) {
  return signIn(request);
}
