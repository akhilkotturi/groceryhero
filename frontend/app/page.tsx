"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Zap, ArrowRight, MapPin, TrendingDown, ShoppingCart } from "lucide-react";
import Link from "next/link";
import { useAuthStore } from "@/lib/store";

export default function LandingPage() {
  const { user } = useAuthStore();
  const router = useRouter();

  useEffect(() => {
    if (user) router.push("/dashboard");
  }, [user, router]);

  return (
    <div className="min-h-screen bg-[var(--bg)] flex flex-col">
      {/* Grid background */}
      <div
        className="absolute inset-0 opacity-[0.025]"
        style={{
          backgroundImage: `linear-gradient(var(--green) 1px, transparent 1px), linear-gradient(90deg, var(--green) 1px, transparent 1px)`,
          backgroundSize: "48px 48px",
        }}
      />

      {/* Glow */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] opacity-20 pointer-events-none"
        style={{
          background: "radial-gradient(ellipse at center, var(--green) 0%, transparent 70%)",
        }}
      />

      {/* Nav */}
      <nav className="relative flex items-center justify-between px-8 py-5">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-[var(--green)] flex items-center justify-center">
            <Zap size={14} className="text-black" />
          </div>
          <span className="font-bold text-lg" style={{ fontFamily: "Syne, sans-serif" }}>
            GroceryHero
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/auth/login"
            className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/auth/register"
            className="flex items-center gap-1.5 px-4 py-2 rounded-[var(--radius)] bg-[var(--green)] text-black text-sm font-semibold hover:bg-[var(--green-dim)] transition-colors"
          >
            Get started <ArrowRight size={13} />
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <main className="relative flex-1 flex flex-col items-center justify-center text-center px-6 pb-24">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-[var(--border)] bg-[var(--bg-card)] text-xs text-[var(--text-secondary)] mb-8">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--green)] animate-pulse" />
            Weekly ads updated every Monday
          </div>

          <h1
            className="text-6xl font-extrabold mb-4 leading-tight"
            style={{ fontFamily: "Syne, sans-serif" }}
          >
            Every deal.
            <br />
            <span className="text-[var(--green)]">One place.</span>
          </h1>

          <p className="text-[var(--text-secondary)] text-lg max-w-md mx-auto mb-10">
            GroceryHero aggregates weekly ads from every store near you, ranks deals by real value, and maps them to your neighborhood.
          </p>

          <Link
            href="/auth/register"
            className="inline-flex items-center gap-2 px-6 py-3.5 rounded-[var(--radius)] bg-[var(--green)] text-black font-semibold hover:bg-[var(--green-dim)] active:scale-[0.98] transition-all"
          >
            Find deals near me <ArrowRight size={16} />
          </Link>
        </motion.div>

        {/* Feature pills */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="flex items-center gap-4 mt-16 flex-wrap justify-center"
        >
          {[
            { icon: MapPin, label: "Mapped to your location" },
            { icon: TrendingDown, label: "ML-ranked by real value" },
            { icon: ShoppingCart, label: "Smart shopping lists" },
          ].map(({ icon: Icon, label }) => (
            <div
              key={label}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-[var(--bg-card)] border border-[var(--border)] text-sm text-[var(--text-secondary)]"
            >
              <Icon size={14} className="text-[var(--green)]" />
              {label}
            </div>
          ))}
        </motion.div>
      </main>
    </div>
  );
}
