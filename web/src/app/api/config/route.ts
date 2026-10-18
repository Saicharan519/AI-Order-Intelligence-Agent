// Tells the browser whether the server supplies the access code (local mode).
// Never returns the code itself.
import { connection } from "next/server";
import { localMode } from "@/lib/server/upstream";

export async function GET() {
  await connection(); // read the environment at request time, not at build time
  return Response.json({ local: localMode() }, { headers: { "cache-control": "no-store" } });
}
