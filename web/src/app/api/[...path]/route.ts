// Backend-for-frontend proxy to the FastAPI service (see src/lib/server/upstream.ts).
import { forward } from "@/lib/server/proxy";

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path);
}

export async function POST(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path);
}
