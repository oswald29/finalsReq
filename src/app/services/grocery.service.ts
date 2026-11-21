import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { catchError, finalize, tap, throwError } from 'rxjs';
import type { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { groceryLineTotal } from '../models/grocery.model';
import type { GroceryItem, GroceryPatch, GroceryPayload } from '../models/grocery.model';
import type { PurchasedHistoryItem } from '../models/purchase-history.model';

@Injectable({
  providedIn: 'root',
})
export class GroceryService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiBaseUrl}/groceries`;
  private readonly itemsState = signal<GroceryItem[]>([]);
  private readonly purchasedHistoryState = signal<PurchasedHistoryItem[]>([]);
  private readonly activeRequests = signal(0);
  private readonly errorState = signal<string | null>(null);

  readonly items = this.itemsState.asReadonly();
  readonly purchasedHistory = this.purchasedHistoryState.asReadonly();
  readonly plannedBudget = computed(() =>
    this.items()
      .filter((item) => !item.purchased)
      .reduce((total, item) => total + groceryLineTotal(item), 0),
  );
  readonly isLoading = computed(() => this.activeRequests() > 0);
  readonly error = this.errorState.asReadonly();

  clear(): void {
    this.itemsState.set([]);
    this.purchasedHistoryState.set([]);
  }

  loadItems(): Observable<GroceryItem[]> {
    return this.trackRequest(
      this.http.get<GroceryItem[]>(this.apiUrl).pipe(tap((items) => this.itemsState.set(items))),
    );
  }

  loadPurchasedHistory(): Observable<PurchasedHistoryItem[]> {
    return this.trackRequest(
      this.http
        .get<PurchasedHistoryItem[]>(`${environment.apiBaseUrl}/purchase-history`)
        .pipe(tap((history) => this.purchasedHistoryState.set(history))),
    );
  }

  deletePurchasedHistoryItem(id: PurchasedHistoryItem['id']): Observable<void> {
    return this.trackRequest(
      this.http
        .delete<void>(`${environment.apiBaseUrl}/purchase-history/${encodeURIComponent(String(id))}`)
        .pipe(tap(() => this.purchasedHistoryState.update((history) => history.filter((item) => item.id !== id)))),
    );
  }

  createItem(item: GroceryPayload): Observable<GroceryItem> {
    return this.trackRequest(
      this.http.post<GroceryItem>(this.apiUrl, item).pipe(tap((created) => this.upsertItem(created))),
    );
  }

  updateItem(id: GroceryItem['id'], item: GroceryPayload): Observable<GroceryItem> {
    return this.trackRequest(
      this.http.put<GroceryItem>(this.getItemUrl(id), item).pipe(tap((updated) => this.upsertItem(updated))),
    );
  }

  patchItem(id: GroceryItem['id'], changes: GroceryPatch): Observable<GroceryItem> {
    return this.trackRequest(
      this.http.patch<GroceryItem>(this.getItemUrl(id), changes).pipe(tap((updated) => this.upsertItem(updated))),
    );
  }

  deleteItem(id: GroceryItem['id']): Observable<void> {
    return this.trackRequest(
      this.http
        .delete<void>(this.getItemUrl(id))
        .pipe(tap(() => this.itemsState.update((items) => items.filter((item) => item.id !== id)))),
    );
  }

  private getItemUrl(id: GroceryItem['id']): string {
    return `${this.apiUrl}/${encodeURIComponent(String(id))}`;
  }

  private upsertItem(item: GroceryItem): void {
    this.itemsState.update((items) => {
      const existing = items.findIndex((current) => current.id === item.id);
      if (existing === -1) {
        return [item, ...items];
      }
      return items.map((current, index) => (index === existing ? item : current));
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
