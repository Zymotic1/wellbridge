/**
 * Auth0 server-side client configuration.
 * Used in Server Components and Route Handlers.
 */

import { initAuth0 } from "@auth0/nextjs-auth0";

const baseURL = process.env.AUTH0_BASE_URL ?? "http://localhost:3000";
const isProd = baseURL.startsWith("https://");

const auth0 = initAuth0({
  secret: process.env.AUTH0_SECRET!,
  baseURL,
  issuerBaseURL: process.env.AUTH0_ISSUER_BASE_URL!,
  clientID: process.env.AUTH0_CLIENT_ID!,
  clientSecret: process.env.AUTH0_CLIENT_SECRET!,
  authorizationParams: {
    audience: process.env.AUTH0_AUDIENCE,
    scope: "openid profile email offline_access",
  },
  session: {
    // Rolling sessions — refresh on each request
    rollingDuration: 60 * 60 * 24,      // 24 hours
    absoluteDuration: 60 * 60 * 24 * 7, // 7 days max
    cookie: {
      sameSite: "lax",
      secure: isProd,
    },
  },
});

export default auth0;

export const { handleAuth, handleLogin, handleLogout, handleCallback, getSession, getAccessToken } = auth0;
