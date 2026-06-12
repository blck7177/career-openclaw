"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { redeemInvite } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { AlertCircle, Loader2 } from "lucide-react";

export default function AuthPage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!code.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await redeemInvite(code.trim());
      router.push("/");
      router.refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Invalid invite code.";
      setError(msg.includes("403") || msg.includes("Forbidden") ? "Invalid or expired invite code." : msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <Card className="w-full max-w-sm shadow-lg">
        <CardHeader className="text-center space-y-1">
          <div className="text-4xl mb-2">🦞</div>
          <CardTitle className="text-xl">OpenClaw</CardTitle>
          <CardDescription>Enter your invite code to access the career intelligence dashboard.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="code">Invite Code</Label>
              <Input
                id="code"
                type="text"
                placeholder="e.g. OPENCLAW-XXXX"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                disabled={loading}
                autoFocus
              />
            </div>
            {error && (
              <div className="flex items-center gap-2 text-sm text-destructive">
                <AlertCircle size={14} />
                {error}
              </div>
            )}
            <Button type="submit" className="w-full" disabled={loading || !code.trim()}>
              {loading ? <><Loader2 size={14} className="mr-2 animate-spin" /> Verifying…</> : "Enter"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
