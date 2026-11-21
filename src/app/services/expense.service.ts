import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { catchError, finalize, tap, throwError } from 'rxjs';
import type { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import type { Expense, ExpensePatch, ExpensePayload } from '../models/expense.model';

@Injectable({
  providedIn: 'root',
})
export class ExpenseService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiBaseUrl}/expenses`;
  private readonly expensesState = signal<Expense[]>([]);
  private readonly activeRequests = signal(0);
  private readonly errorState = signal<string | null>(null);

  readonly expenses = this.expensesState.asReadonly();
  readonly isLoading = computed(() => this.activeRequests() > 0);
  readonly error = this.errorState.asReadonly();

  clear(): void {
    this.expensesState.set([]);
  }

  loadExpenses(): Observable<Expense[]> {
    return this.trackRequest(
      this.http.get<Expense[]>(this.apiUrl).pipe(tap((expenses) => this.expensesState.set(expenses))),
    );
  }

  getExpense(id: Expense['id']): Observable<Expense> {
    return this.trackRequest(
      this.http.get<Expense>(this.getExpenseUrl(id)).pipe(tap((expense) => this.upsertExpense(expense))),
    );
  }

  createExpense(expense: ExpensePayload): Observable<Expense> {
    return this.trackRequest(
      this.http.post<Expense>(this.apiUrl, expense).pipe(tap((createdExpense) => this.upsertExpense(createdExpense))),
    );
  }

  updateExpense(id: Expense['id'], expense: ExpensePayload): Observable<Expense> {
    return this.trackRequest(
      this.http
        .put<Expense>(this.getExpenseUrl(id), expense)
        .pipe(tap((updatedExpense) => this.upsertExpense(updatedExpense))),
    );
  }

  patchExpense(id: Expense['id'], changes: ExpensePatch): Observable<Expense> {
    return this.trackRequest(
      this.http
        .patch<Expense>(this.getExpenseUrl(id), changes)
        .pipe(tap((updatedExpense) => this.upsertExpense(updatedExpense))),
    );
  }

  deleteExpense(id: Expense['id']): Observable<void> {
    return this.trackRequest(
      this.http
        .delete<void>(this.getExpenseUrl(id))
        .pipe(tap(() => this.expensesState.update((expenses) => expenses.filter((expense) => expense.id !== id)))),
    );
  }

  private getExpenseUrl(id: Expense['id']): string {
    return `${this.apiUrl}/${encodeURIComponent(String(id))}`;
  }

  private upsertExpense(expense: Expense): void {
    this.expensesState.update((expenses) => {
      const existingIndex = expenses.findIndex((item) => item.id === expense.id);
      if (existingIndex === -1) {
        return [...expenses, expense];
      }

      return expenses.map((item, index) => (index === existingIndex ? expense : item));
    });
  }

  private trackRequest<T>(request: Observable<T>): Observable<T> {
    this.errorState.set(null);
    this.activeRequests.update((count) => count + 1);

    return request.pipe(
      catchError((error: unknown) => {
        this.errorState.set(error instanceof HttpErrorResponse ? error.message : 'An unexpected error occurred.');
        return throwError(() => error);
      }),
      finalize(() => this.activeRequests.update((count) => count - 1)),
    );
  }
}
