import { isPlatformBrowser } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { computed, inject, Injectable, PLATFORM_ID, signal } from '@angular/core';
import { finalize, of, tap } from 'rxjs';
import type { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import type { AuthResponse, AuthUser, LoginPayload, RegisterPayload } from '../models/auth.model';

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));
  private readonly apiUrl = `${environment.apiBaseUrl}/auth`;
  private readonly tokenState = signal(this.readStoredToken());
  private readonly userState = signal<AuthUser | null>(null);

  readonly token = this.tokenState.asReadonly();
  readonly user = this.userState.asReadonly();
  readonly isAuthenticated = computed(() => this.token() !== null);

  register(payload: RegisterPayload): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.apiUrl}/register`, payload)
      .pipe(tap((response) => this.setSession(response)));
  }

  login(payload: LoginPayload): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.apiUrl}/login`, payload)
      .pipe(tap((response) => this.setSession(response)));
  }

  loadCurrentUser(): Observable<AuthUser> {
    return this.http.get<AuthUser>(`${this.apiUrl}/me`).pipe(tap((user) => this.userState.set(user)));
  }

  updateMonthlyBudget(monthlyBudget: number): Observable<AuthUser> {
    return this.http
      .put<AuthUser>(`${this.apiUrl}/me`, { monthlyBudget })
      .pipe(tap((user) => this.userState.set(user)));
  }

  logout(): Observable<void> {
    if (!this.token()) {
      this.clearSession();
      return of(void 0);
    }

    return this.http.post<void>(`${this.apiUrl}/logout`, {}).pipe(
      finalize(() => this.clearSession()),
    );
  }

  clearSession(): void {
    this.tokenState.set(null);
    this.userState.set(null);
    if (this.isBrowser) {
      localStorage.removeItem('expense_tracker_token');
    }
  }

  private setSession(response: AuthResponse): void {
    this.tokenState.set(response.token);
    this.userState.set(response.user);
    if (this.isBrowser) {
      localStorage.setItem('expense_tracker_token', response.token);
    }
  }

  private readStoredToken(): string | null {
    return this.isBrowser ? localStorage.getItem('expense_tracker_token') : null;
  }
}
