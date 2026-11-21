export interface Expense {
  id: string | number;
  title: string;
  amount: number;
  category: string;
  date: string;
  notes: string;
  purchasedAt?: string | null;
}

export type ExpensePayload = Omit<Expense, 'id' | 'purchasedAt'>;
export type ExpensePatch = Partial<ExpensePayload>;
