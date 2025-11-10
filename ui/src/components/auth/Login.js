import React, { useState } from 'react';

// Shared styles for consistency
const styles = {
  pageContainer: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'linear-gradient(135deg, #3d4a5c 0%, #2a3441 50%, #2e3947 100%)'
  },
  card: {
    maxWidth: '28rem',
    width: '100%',
    padding: '2.5rem',
    background: 'white',
    borderRadius: '12px',
    boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.3)',
    border: '1px solid rgba(151, 202, 111, 0.2)'
  },
  title: {
    marginTop: '1.5rem',
    textAlign: 'center',
    fontSize: '1.875rem',
    fontWeight: '700',
    color: '#1a202c',
    marginBottom: '0.5rem'
  },
  subtitle: {
    marginTop: '0.5rem',
    textAlign: 'center',
    fontSize: '0.875rem',
    color: '#4a5568'
  },
  form: {
    marginTop: '2rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '1.5rem'
  },
  errorBox: {
    borderRadius: '8px',
    background: 'linear-gradient(135deg, #fed7d7, #fcbdbd)',
    padding: '1rem',
    border: '1px solid #fc8181',
    fontSize: '0.875rem',
    color: '#742a2a'
  },
  successBox: {
    borderRadius: '8px',
    background: 'linear-gradient(135deg, #d4edc4, #c5e4b5)',
    padding: '1rem',
    border: '1px solid #97CA6F',
    fontSize: '0.875rem',
    color: '#2d3748'
  },
  input: {
    width: '100%',
    padding: '0.625rem 0.75rem',
    fontSize: '0.875rem',
    border: '1px solid #e2e8f0',
    borderRadius: '8px',
    transition: 'all 0.3s ease',
    fontFamily: 'inherit'
  },
  button: (loading) => ({
    width: '100%',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    padding: '0.625rem 1rem',
    border: 'none',
    fontSize: '0.875rem',
    fontWeight: '600',
    borderRadius: '8px',
    background: loading ? 'linear-gradient(135deg, #a8d67f, #97CA6F)' : 'linear-gradient(135deg, #97CA6F, #7db555)',
    color: '#3d4a5c',
    cursor: loading ? 'not-allowed' : 'pointer',
    transition: 'all 0.3s ease',
    boxShadow: '0 2px 4px rgba(151, 202, 111, 0.2)'
  }),
  linkButton: {
    background: 'none',
    border: 'none',
    fontSize: '0.875rem',
    fontWeight: '500',
    color: '#718096',
    cursor: 'pointer',
    transition: 'color 0.3s ease'
  },
  linkButtonPrimary: {
    background: 'none',
    border: 'none',
    fontSize: '0.875rem',
    fontWeight: '500',
    color: '#97CA6F',
    cursor: 'pointer',
    transition: 'color 0.3s ease'
  }
};

const handleInputFocus = (e) => {
  e.target.style.borderColor = '#97CA6F';
  e.target.style.boxShadow = '0 0 0 3px rgba(151, 202, 111, 0.1)';
};

const handleInputBlur = (e) => {
  e.target.style.borderColor = '#e2e8f0';
  e.target.style.boxShadow = 'none';
};

const handleButtonHover = (e, loading) => {
  if (!loading) {
    e.target.style.boxShadow = '0 4px 12px rgba(151, 202, 111, 0.3)';
    e.target.style.transform = 'translateY(-1px)';
  }
};

const handleButtonLeave = (e) => {
  e.target.style.boxShadow = '0 2px 4px rgba(151, 202, 111, 0.2)';
  e.target.style.transform = 'translateY(0)';
};

function Login({ onLoginSuccess }) {
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [showForgotPassword, setShowForgotPassword] = useState(false);
  const [showResetPassword, setShowResetPassword] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmationCode, setConfirmationCode] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMessage('');
    setLoading(true);

    try {
      const response = await fetch('../auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        // Check if user needs email confirmation
        if (response.status === 403 && data.detail.includes('not confirmed')) {
          setShowConfirmation(true);
          setSuccessMessage('Please verify your email. Check your inbox for the verification code.');
          setLoading(false);
          return;
        }
        throw new Error(data.detail || 'Authentication failed');
      }

      // Login successful - cookies are set automatically
      onLoginSuccess();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmation = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMessage('');
    setLoading(true);

    try {
      const response = await fetch('../auth/confirm-signup', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email,
          confirmation_code: confirmationCode
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Confirmation failed');
      }

      setSuccessMessage('Email verified successfully! You can now log in.');
      setShowConfirmation(false);
      setConfirmationCode('');
      setPassword('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleResendCode = async () => {
    setError('');
    setSuccessMessage('');
    setLoading(true);

    try {
      const response = await fetch('../auth/resend-confirmation', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to resend code');
      }

      setSuccessMessage(data.message || 'Verification code resent to your email.');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleForgotPassword = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMessage('');
    setLoading(true);

    try {
      const response = await fetch('../auth/forgot-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to send reset code');
      }

      setSuccessMessage(data.message || 'Password reset code sent to your email.');
      setShowForgotPassword(false);
      setShowResetPassword(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmReset = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMessage('');
    setLoading(true);

    try {
      const response = await fetch('../auth/confirm-forgot-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email,
          confirmation_code: confirmationCode,
          new_password: newPassword
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to reset password');
      }

      setSuccessMessage('Password reset successfully! You can now log in with your new password.');
      setShowResetPassword(false);
      setConfirmationCode('');
      setNewPassword('');
      setPassword('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Forgot password panel
  if (showForgotPassword) {
    return (
      <div style={styles.pageContainer}>
        <div style={styles.card}>
          <div>
            <h2 style={styles.title}>Reset Password</h2>
            <p style={styles.subtitle}>
              Enter your email to receive a password reset code
            </p>
          </div>

          <form style={styles.form} onSubmit={handleForgotPassword}>
            {error && <div style={styles.errorBox}>{error}</div>}
            {successMessage && <div style={styles.successBox}>{successMessage}</div>}

            <div>
              <label htmlFor="email-reset" style={{ position: 'absolute', width: '1px', height: '1px', overflow: 'hidden' }}>
                Email address
              </label>
              <input
                id="email-reset"
                name="email"
                type="email"
                required
                style={styles.input}
                placeholder="Email address"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onFocus={handleInputFocus}
                onBlur={handleInputBlur}
              />
            </div>

            <div>
              <button
                type="submit"
                disabled={loading}
                style={styles.button(loading)}
                onMouseOver={(e) => handleButtonHover(e, loading)}
                onMouseOut={handleButtonLeave}
              >
                {loading ? 'Sending...' : 'Send Reset Code'}
              </button>
            </div>

            <div style={{ textAlign: 'center' }}>
              <button
                type="button"
                onClick={() => {
                  setShowForgotPassword(false);
                  setError('');
                  setSuccessMessage('');
                }}
                style={styles.linkButton}
                onMouseOver={(e) => e.target.style.color = '#4a5568'}
                onMouseOut={(e) => e.target.style.color = '#718096'}
              >
                Back to login
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  // Reset password confirmation panel
  if (showResetPassword) {
    return (
      <div style={styles.pageContainer}>
        <div style={styles.card}>
          <div>
            <h2 style={styles.title}>Set New Password</h2>
            <p style={styles.subtitle}>
              Enter the code sent to <span style={{ fontWeight: '500' }}>{email}</span> and your new password
            </p>
          </div>

          <form style={styles.form} onSubmit={handleConfirmReset}>
            {error && <div style={styles.errorBox}>{error}</div>}
            {successMessage && <div style={styles.successBox}>{successMessage}</div>}

            <div>
              <label htmlFor="reset-code" style={{ position: 'absolute', width: '1px', height: '1px', overflow: 'hidden' }}>
                Verification Code
              </label>
              <input
                id="reset-code"
                name="code"
                type="text"
                required
                style={styles.input}
                placeholder="Verification code"
                value={confirmationCode}
                onChange={(e) => setConfirmationCode(e.target.value)}
                onFocus={handleInputFocus}
                onBlur={handleInputBlur}
              />
            </div>

            <div>
              <label htmlFor="new-password" style={{ position: 'absolute', width: '1px', height: '1px', overflow: 'hidden' }}>
                New Password
              </label>
              <input
                id="new-password"
                name="newPassword"
                type="password"
                required
                style={styles.input}
                placeholder="New password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                onFocus={handleInputFocus}
                onBlur={handleInputBlur}
              />
            </div>

            <div>
              <button
                type="submit"
                disabled={loading}
                style={styles.button(loading)}
                onMouseOver={(e) => handleButtonHover(e, loading)}
                onMouseOut={handleButtonLeave}
              >
                {loading ? 'Resetting...' : 'Reset Password'}
              </button>
            </div>

            <div style={{ textAlign: 'center' }}>
              <button
                type="button"
                onClick={() => {
                  setShowResetPassword(false);
                  setShowForgotPassword(true);
                  setConfirmationCode('');
                  setNewPassword('');
                  setError('');
                  setSuccessMessage('');
                }}
                style={styles.linkButton}
                onMouseOver={(e) => e.target.style.color = '#4a5568'}
                onMouseOut={(e) => e.target.style.color = '#718096'}
              >
                Back
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  // Confirmation panel
  if (showConfirmation) {
    return (
      <div style={styles.pageContainer}>
        <div style={styles.card}>
          <div>
            <h2 style={styles.title}>Verify Your Email</h2>
            <p style={styles.subtitle}>
              We sent a verification code to <span style={{ fontWeight: '500' }}>{email}</span>
            </p>
          </div>

          <form style={styles.form} onSubmit={handleConfirmation}>
            {error && <div style={styles.errorBox}>{error}</div>}
            {successMessage && <div style={styles.successBox}>{successMessage}</div>}

            <div>
              <label htmlFor="confirmation-code" style={{ position: 'absolute', width: '1px', height: '1px', overflow: 'hidden' }}>
                Verification Code
              </label>
              <input
                id="confirmation-code"
                name="code"
                type="text"
                required
                style={styles.input}
                placeholder="Enter verification code"
                value={confirmationCode}
                onChange={(e) => setConfirmationCode(e.target.value)}
                onFocus={handleInputFocus}
                onBlur={handleInputBlur}
              />
            </div>

            <div>
              <button
                type="submit"
                disabled={loading}
                style={styles.button(loading)}
                onMouseOver={(e) => handleButtonHover(e, loading)}
                onMouseOut={handleButtonLeave}
              >
                {loading ? 'Verifying...' : 'Verify Email'}
              </button>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.875rem' }}>
              <button
                type="button"
                onClick={handleResendCode}
                disabled={loading}
                style={styles.linkButtonPrimary}
                onMouseOver={(e) => !loading && (e.target.style.color = '#7db555')}
                onMouseOut={(e) => (e.target.style.color = '#97CA6F')}
              >
                Resend code
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowConfirmation(false);
                  setConfirmationCode('');
                  setError('');
                  setSuccessMessage('');
                }}
                style={styles.linkButton}
                onMouseOver={(e) => e.target.style.color = '#4a5568'}
                onMouseOut={(e) => e.target.style.color = '#718096'}
              >
                Back to login
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  // Main login panel
  return (
    <div style={styles.pageContainer}>
      <div style={styles.card}>
        <div>
          <h2 style={styles.title}>Sign in to your account</h2>
        </div>

        <form style={styles.form} onSubmit={handleSubmit}>
          {error && <div style={styles.errorBox}>{error}</div>}
          {successMessage && <div style={styles.successBox}>{successMessage}</div>}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
            <div>
              <label htmlFor="email-address" style={{ position: 'absolute', width: '1px', height: '1px', overflow: 'hidden' }}>
                Email address
              </label>
              <input
                id="email-address"
                name="email"
                type="email"
                autoComplete="email"
                required
                style={{
                  ...styles.input,
                  borderBottomLeftRadius: '0',
                  borderBottomRightRadius: '0'
                }}
                placeholder="Email address"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onFocus={handleInputFocus}
                onBlur={handleInputBlur}
              />
            </div>
            <div>
              <label htmlFor="password" style={{ position: 'absolute', width: '1px', height: '1px', overflow: 'hidden' }}>
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                style={{
                  ...styles.input,
                  borderTopLeftRadius: '0',
                  borderTopRightRadius: '0',
                  borderTop: 'none'
                }}
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onFocus={handleInputFocus}
                onBlur={handleInputBlur}
              />
            </div>
          </div>

          <div>
            <button
              type="submit"
              disabled={loading}
              style={styles.button(loading)}
              onMouseOver={(e) => handleButtonHover(e, loading)}
              onMouseOut={handleButtonLeave}
            >
              {loading ? 'Processing...' : 'Sign in'}
            </button>
          </div>

          <div style={{ textAlign: 'center' }}>
            <button
              type="button"
              onClick={() => {
                setShowForgotPassword(true);
                setError('');
                setSuccessMessage('');
              }}
              style={styles.linkButtonPrimary}
              onMouseOver={(e) => e.target.style.color = '#7db555'}
              onMouseOut={(e) => e.target.style.color = '#97CA6F'}
            >
              Forgot your password?
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default Login;
