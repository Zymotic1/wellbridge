/**
 * Supabase browser client.
 *
 * IMPORTANT: This client uses the public anon key and is safe for browser use.
 * RLS policies are enforced at the database level using the JWT from Auth0.
 *
 * For server-side use (Route Handlers, Server Components), use the server
 * client with the user's access token attached.
 */

import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

// Browser client — reuse a single instance
export const supabase = createClient(supabaseUrl, supabaseAnonKey);

/**
 * Creates a Supabase client authenticated with the user's Auth0 access token.
 * Call this inside server-side code where you have the token available.
 */
export function createAuthenticatedClient(accessToken: string) {
  return createClient(supabaseUrl, supabaseAnonKey, {
    global: {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    },
  });
}
