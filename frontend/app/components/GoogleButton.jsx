"use client";
import { useEffect, useRef } from "react";
import { GOOGLE_CLIENT_ID } from "@/lib/api";

export default function GoogleButton({ onCredential }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    function init() {
      if (!window.google || !ref.current) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (resp) => onCredential(resp.credential),
      });
      window.google.accounts.id.renderButton(ref.current, {
        theme: "outline", size: "large", width: 320, text: "continue_with", shape: "pill",
      });
    }
    if (document.getElementById("gsi-script")) { init(); return; }
    const s = document.createElement("script");
    s.id = "gsi-script";
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true; s.defer = true; s.onload = init;
    document.body.appendChild(s);
  }, [onCredential]);

  if (!GOOGLE_CLIENT_ID) {
    return (
      <div className="text-center text-xs text-muted">
        Set <code>NEXT_PUBLIC_GOOGLE_CLIENT_ID</code> in frontend/.env.local to enable Google sign-in
      </div>
    );
  }
  return <div ref={ref} className="flex justify-center" />;
}
