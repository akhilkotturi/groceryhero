"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Zap, ArrowRight } from "lucide-react";
import Link from "next/link";
import { useAuthStore } from "@/lib/store";
import { cn, getApiErrorMessage } from "@/lib/utils";

export default function LoginPage() {
  const { login, isLoading } = useAuthStore();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    setError("");
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err: any) {
      setError(getApiErrorMessage(err, "Login failed"));
    }
  };

  return (
    <div className="min-h-screen bg-[var(--bg)] flex items-center justify-center p-4">
      {/* Background grid */}
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: `linear-gradient(var(--green) 1px, transparent 1px), linear-gradient(90deg, var(--green) 1px, transparent 1px)`,
          backgroundSize: "40px 40px",
        }}
      />

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="relative w-full max-w-sm"
      >
        {/* Logo */}
        <div className="flex items-center gap-2 mb-8">
          <div className="w-8 h-8 rounded-lg bg-[var(--green)] flex items-center justify-center">
            <Zap size={16} className="text-black" />
          </div>
          <span className="font-bold text-xl" style={{ fontFamily: "Syne, sans-serif" }}>
            GroceryHero
          </span>
        </div>

        <h1
          className="text-3xl font-bold mb-1"
          style={{ fontFamily: "Syne, sans-serif" }}
        >
          Welcome back
        </h1>
        <p className="text-[var(--text-secondary)] text-sm mb-8">
          Sign in to see this week's best deals near you
        </p>

        <div className="space-y-3">
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-[var(--radius)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--green)] transition-colors"
            suppressHydrationWarning
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-[var(--radius)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--green)] transition-colors"
            suppressHydrationWarning
          />

          {error && (
            <p className="text-[var(--red)] text-xs">{error}</p>
          )}

          <button
            onClick={handleSubmit}
            disabled={isLoading || !email || !password}
            className={cn(
              "w-full flex items-center justify-center gap-2 py-3 rounded-[var(--radius)] text-sm font-semibold transition-all",
              isLoading || !email || !password
                ? "bg-[var(--bg-elevated)] text-[var(--text-muted)] cursor-not-allowed"
                : "bg-[var(--green)] text-black hover:bg-[var(--green-dim)] active:scale-[0.98]"
            )}
          >
            {isLoading ? "Signing in..." : "Sign in"}
            {!isLoading && <ArrowRight size={14} />}
          </button>
        </div>

        <p className="text-center text-sm text-[var(--text-muted)] mt-6">
          No account?{" "}
          <Link href="/auth/register" className="text-[var(--green)] hover:underline">
            Create one
          </Link>
        </p>
      </motion.div>
    </div>
  );
}
