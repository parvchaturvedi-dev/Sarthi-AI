"use client";
import { useEffect, useRef } from "react";
import { GOOGLE_CLIENT_ID } from "@/lib/api";

// Google Identity Services in FedCM-only mode: no cross-origin popup, so no
// `Cross-Origin-Opener-Policy would block window.postMessage` warning ever
// shows up in the console.
export default function GoogleButton({ onCredential }) {
  const ref = useRef(null);
  const initedRef = useRef(false);       // don't re-initialize on re-renders

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    function init() {
      if (!window.google || !ref.current || initedRef.current) return;
      initedRef.current = true;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (resp) => onCredential(resp.credential),
        use_fedcm_for_prompt: true,      // native browser sign-in dialog
        use_fedcm_for_button: true,      // button click uses FedCM (no popup)
        ux_mode: "popup",                // still popup fallback if FedCM unavailable
        auto_select: false,
        itp_support: true,
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
