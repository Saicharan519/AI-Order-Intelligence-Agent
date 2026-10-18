// Sign-in, emailed-code and password-reset steps (see authFlow in src/lib/server/proxy.ts):
// talks to the API and keeps the session, challenge and trusted-device tokens in httpOnly cookies.
import { authFlow } from "@/lib/server/proxy";

type Ctx = { params: Promise<{ action: string }> };

export async function POST(request: Request, ctx: Ctx) {
  return authFlow(request, (await ctx.params).action);
}
