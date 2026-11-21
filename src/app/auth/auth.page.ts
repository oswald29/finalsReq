import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { IonButton, IonContent, IonIcon, IonInput, IonItem } from '@ionic/angular';
import { finalize } from 'rxjs';

import { AuthService } from '../services/auth.service';

@Component({
  selector: 'app-auth',
  templateUrl: './auth.page.html',
  imports: [IonButton, IonContent, IonIcon, IonInput, IonItem],
})
export class AuthPage {
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);

  readonly isRegistering = signal(false);
  readonly name = signal('');
  readonly email = signal('');
  readonly password = signal('');
  readonly isSubmitting = signal(false);
  readonly error = signal<string | null>(null);
  readonly canSubmit = computed(
    () =>
      this.email().trim().length > 0 &&
      this.password().length >= 8 &&
      (!this.isRegistering() || this.name().trim().length > 0),
  );

  setName(value: string | null | undefined): void {
    this.name.set(value ?? '');
  }

  setEmail(value: string | null | undefined): void {
    this.email.set(value ?? '');
  }

  setPassword(value: string | null | undefined): void {
    this.password.set(value ?? '');
  }

  toggleMode(): void {
    this.isRegistering.update((registering) => !registering);
    this.error.set(null);
  }

  submit(event: SubmitEvent): void {
    event.preventDefault();
    if (!this.canSubmit() || this.isSubmitting()) {
      return;
    }

    this.error.set(null);
    this.isSubmitting.set(true);
    const request = this.isRegistering()
      ? this.authService.register({
          name: this.name().trim(),
          email: this.email().trim(),
          password: this.password(),
        })
      : this.authService.login({
          email: this.email().trim(),
          password: this.password(),
        });

    request.pipe(finalize(() => this.isSubmitting.set(false))).subscribe({
      next: () => void this.router.navigateByUrl('/home'),
      error: (error: unknown) => this.error.set(this.getErrorMessage(error)),
    });
  }

  private getErrorMessage(error: unknown): string {
    if (error instanceof HttpErrorResponse && typeof error.error?.error === 'string') {
      return error.error.error;
    }
    return 'Could not connect to the server. Check that the API is running and try again.';
  }
}
