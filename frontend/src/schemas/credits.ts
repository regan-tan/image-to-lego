import { z } from "zod";

export const creditTransactionSchema = z.object({
  id: z.string(),
  kind: z.enum(["starter_grant", "job_charge", "job_refund", "admin_grant"]),
  amount: z.number().int(),
  balanceAfter: z.number().int().nonnegative(),
  createdAt: z.string(),
});

export const creditsSchema = z.object({
  balance: z.number().int().nonnegative(),
  reconstructionCost: z.number().int().positive(),
  conversionCost: z.number().int().positive(),
  transactions: z.array(creditTransactionSchema),
});

export type Credits = z.infer<typeof creditsSchema>;
