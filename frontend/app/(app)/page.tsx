import { redirect } from "next/navigation";

// Default authenticated route → Home
export default function AppRoot() {
  redirect("/home");
}
