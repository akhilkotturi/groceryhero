"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Zap, ArrowRight, ArrowLeft, MapPin, Users, DollarSign, Check } from "lucide-react";
import Link from "next/link";
import { useAuthStore } from "@/lib/store";
import api from "@/lib/api";
import { cn, getApiErrorMessage } from "@/lib/utils";

type Step = "account" | "location" | "preferences" | "done";

const STEPS: Step[] = ["account", "location", "preferences", "done"];

const DIETARY_OPTIONS = [
  "Vegetarian", "Vegan", "Gluten-free", "Dairy-free",
  "Nut-free", "Halal", "Kosher", "Low-sodium",
];

export default function RegisterPage() {
  const { register, isLoading, user } = useAuthStore();
  const router = useRouter();

  const [step, setStep] = useState<Step>("account");
  const [error, setError] = useState("");

  // Account fields
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // Location fields
  const [zipCode, setZipCode] = useState("");

  // Preference fields
  const [householdSize, setHouseholdSize] = useState(2);
  const [weeklyBudget, setWeeklyBudget] = useState(150);
  const [dietary, setDietary] = useState<string[]>([]);

  const stepIndex = STEPS.indexOf(step);

  const handleAccountNext = async () => {
    setError("");
    try {
      await register(email, username, password);
      setStep("location");
    } catch (err: any) {
      setError(getApiErrorMessage(err, "Registration failed"));
    }
  };

  const handleLocationNext = async () => {
    setError("");
    try {
      await api.patch("/api/users/me", { zip_code: zipCode });
      setStep("preferences");
    } catch {
      // Non-fatal, continue
      setStep("preferences");
    }
  };

  const handlePreferencesNext = async () => {
    setError("");
    try {
      await api.patch("/api/users/me", {
        household_size: householdSize,
        weekly_budget: weeklyBudget,
        dietary_restrictions: dietary,
      });
    } catch {
      // Non-fatal
    }
    setStep("done");
    setTimeout(() => router.push("/dashboard"), 1200);
  };

  const toggleDietary = (option: string) => {
    setDietary((prev) =>
      prev.includes(option) ? prev.filter((d) => d !== option) : [...prev, option]
    );
  };

  return (
    <div className="min-h-screen bg-[var(--bg)] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: `linear-gradient(var(--green) 1px, transparent 1px), linear-gradient(90deg, var(--green) 1px, transparent 1px)`,
          backgroundSize: "40px 40px",
        }}
      />

      <div className="relative w-full max-w-sm">
        {/* Logo */}
        <div className="flex items-center gap-2 mb-8">
          <div className="w-8 h-8 rounded-lg bg-[var(--green)] flex items-center justify-center">
            <Zap size={16} className="text-black" />
          </div>
          <span className="font-bold text-xl" style={{ fontFamily: "Syne, sans-serif" }}>
            GroceryHero
          </span>
        </div>

        {/* Progress bar */}
        {step !== "done" && (
          <div className="flex gap-1.5 mb-8">
            {STEPS.slice(0, -1).map((s, i) => (
              <div
                key={s}
                className={cn(
                  "h-0.5 flex-1 rounded-full transition-all duration-300",
                  i <= stepIndex - (step === "done" ? 0 : 0)
                    ? "bg-[var(--green)]"
                    : "bg-[var(--border)]"
                )}
              />
            ))}
          </div>
        )}

        <AnimatePresence mode="wait">
          {/* Step 1: Account */}
          {step === "account" && (
            <motion.div
              key="account"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.25 }}
            >
              <h1 className="text-3xl font-bold mb-1" style={{ fontFamily: "Syne, sans-serif" }}>
                Create account
              </h1>
              <p className="text-[var(--text-secondary)] text-sm mb-8">
                Start finding deals in your neighborhood
              </p>

              <div className="space-y-3">
                <input
                  type="email"
                  placeholder="Email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-[var(--radius)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--green)] transition-colors"
                />
                <input
                  type="text"
                  placeholder="Username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-[var(--radius)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--green)] transition-colors"
                />
                <input
                  type="password"
                  placeholder="Password (8+ characters)"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAccountNext()}
                  className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-[var(--radius)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--green)] transition-colors"
                />

                {error && <p className="text-[var(--red)] text-xs">{error}</p>}

                <button
                  onClick={handleAccountNext}
                  disabled={isLoading || !email || !username || !password}
                  className={cn(
                    "w-full flex items-center justify-center gap-2 py-3 rounded-[var(--radius)] text-sm font-semibold transition-all",
                    isLoading || !email || !username || !password
                      ? "bg-[var(--bg-elevated)] text-[var(--text-muted)] cursor-not-allowed"
                      : "bg-[var(--green)] text-black hover:bg-[var(--green-dim)] active:scale-[0.98]"
                  )}
                >
                  {isLoading ? "Creating account..." : "Continue"}
                  {!isLoading && <ArrowRight size={14} />}
                </button>
              </div>

              <p className="text-center text-sm text-[var(--text-muted)] mt-6">
                Already have an account?{" "}
                <Link href="/auth/login" className="text-[var(--green)] hover:underline">
                  Sign in
                </Link>
              </p>
            </motion.div>
          )}

          {/* Step 2: Location */}
          {step === "location" && (
            <motion.div
              key="location"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.25 }}
            >
              <div className="w-10 h-10 rounded-xl bg-[var(--green-glow)] border border-[var(--green)] flex items-center justify-center mb-6">
                <MapPin size={18} className="text-[var(--green)]" />
              </div>

              <h1 className="text-3xl font-bold mb-1" style={{ fontFamily: "Syne, sans-serif" }}>
                Where are you?
              </h1>
              <p className="text-[var(--text-secondary)] text-sm mb-8">
                We use your zip code to find stores and deals near you
              </p>

              <div className="space-y-3">
                <input
                  type="text"
                  placeholder="Zip code (e.g. 78701)"
                  value={zipCode}
                  onChange={(e) => setZipCode(e.target.value.replace(/\D/g, "").slice(0, 5))}
                  onKeyDown={(e) => e.key === "Enter" && zipCode.length === 5 && handleLocationNext()}
                  className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-[var(--radius)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--green)] transition-colors font-mono tracking-widest"
                />

                <button
                  onClick={handleLocationNext}
                  disabled={zipCode.length !== 5}
                  className={cn(
                    "w-full flex items-center justify-center gap-2 py-3 rounded-[var(--radius)] text-sm font-semibold transition-all",
                    zipCode.length !== 5
                      ? "bg-[var(--bg-elevated)] text-[var(--text-muted)] cursor-not-allowed"
                      : "bg-[var(--green)] text-black hover:bg-[var(--green-dim)] active:scale-[0.98]"
                  )}
                >
                  Continue <ArrowRight size={14} />
                </button>

                <button
                  onClick={() => setStep("preferences")}
                  className="w-full py-3 text-sm text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
                >
                  Skip for now
                </button>
              </div>
            </motion.div>
          )}

          {/* Step 3: Preferences */}
          {step === "preferences" && (
            <motion.div
              key="preferences"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.25 }}
            >
              <div className="w-10 h-10 rounded-xl bg-[var(--green-glow)] border border-[var(--green)] flex items-center justify-center mb-6">
                <Users size={18} className="text-[var(--green)]" />
              </div>

              <h1 className="text-3xl font-bold mb-1" style={{ fontFamily: "Syne, sans-serif" }}>
                Your household
              </h1>
              <p className="text-[var(--text-secondary)] text-sm mb-8">
                Helps us rank deals that matter to you
              </p>

              <div className="space-y-6">
                {/* Household size */}
                <div>
                  <label className="text-xs uppercase tracking-widest text-[var(--text-muted)] mb-3 block">
                    Household size
                  </label>
                  <div className="flex gap-2">
                    {[1, 2, 3, 4, 5, 6].map((n) => (
                      <button
                        key={n}
                        onClick={() => setHouseholdSize(n)}
                        className={cn(
                          "flex-1 py-2 rounded-[var(--radius-sm)] text-sm font-medium transition-all",
                          householdSize === n
                            ? "bg-[var(--green)] text-black"
                            : "bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--text-muted)]"
                        )}
                      >
                        {n === 6 ? "6+" : n}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Weekly budget */}
                <div>
                  <label className="text-xs uppercase tracking-widest text-[var(--text-muted)] mb-3 block">
                    Weekly grocery budget
                  </label>
                  <div className="flex items-center gap-3">
                    <DollarSign size={14} className="text-[var(--green)] shrink-0" />
                    <input
                      type="range"
                      min={25}
                      max={500}
                      step={25}
                      value={weeklyBudget}
                      onChange={(e) => setWeeklyBudget(Number(e.target.value))}
                      className="flex-1 accent-[var(--green)]"
                    />
                    <span className="text-sm font-mono text-[var(--text-primary)] w-16 text-right">
                      ${weeklyBudget}
                    </span>
                  </div>
                </div>

                {/* Dietary restrictions */}
                <div>
                  <label className="text-xs uppercase tracking-widest text-[var(--text-muted)] mb-3 block">
                    Dietary restrictions (optional)
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {DIETARY_OPTIONS.map((opt) => (
                      <button
                        key={opt}
                        onClick={() => toggleDietary(opt)}
                        className={cn(
                          "px-3 py-1.5 rounded-full text-xs transition-all",
                          dietary.includes(opt)
                            ? "bg-[var(--green-glow)] text-[var(--green)] border border-[var(--green)]"
                            : "bg-[var(--bg-card)] text-[var(--text-secondary)] border border-[var(--border)] hover:border-[var(--text-muted)]"
                        )}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>

                <button
                  onClick={handlePreferencesNext}
                  className="w-full flex items-center justify-center gap-2 py-3 rounded-[var(--radius)] text-sm font-semibold bg-[var(--green)] text-black hover:bg-[var(--green-dim)] active:scale-[0.98] transition-all"
                >
                  Find deals <ArrowRight size={14} />
                </button>
              </div>
            </motion.div>
          )}

          {/* Done */}
          {step === "done" && (
            <motion.div
              key="done"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3 }}
              className="text-center py-8"
            >
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: "spring", stiffness: 200, delay: 0.1 }}
                className="w-16 h-16 rounded-full bg-[var(--green)] flex items-center justify-center mx-auto mb-6"
              >
                <Check size={28} className="text-black" />
              </motion.div>
              <h2 className="text-2xl font-bold mb-2" style={{ fontFamily: "Syne, sans-serif" }}>
                You're in
              </h2>
              <p className="text-[var(--text-secondary)] text-sm">
                Loading your deals...
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
