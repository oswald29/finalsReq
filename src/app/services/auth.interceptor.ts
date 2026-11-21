import { HttpErrorResponse, type HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { environment } from '../../environments/environment';

import { AuthService } from './auth.service';

export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const authService = inject(AuthService);
  const router = inject(Router);
  const token = authService.token();
  const isApiRequest = request.url.startsWith(environment.apiBaseUrl);
  const authenticatedRequest =
    isApiRequest && token ? request.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : request;
  const isCredentialRequest = request.url.endsWith('/auth/login') || request.url.endsWith('/auth/register');

  return next(authenticatedRequest).pipe(
    catchError((error: unknown) => {
      if (error instanceof HttpErrorResponse && error.status === 401 && isApiRequest && !isCredentialRequest) {
        authService.clearSession();
        void router.navigateByUrl('/auth');
      }
      return throwError(() => error);
    }),
  );
};
