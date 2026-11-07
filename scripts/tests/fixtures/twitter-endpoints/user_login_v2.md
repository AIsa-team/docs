> ## Documentation Index
> Fetch the complete documentation index at: https://docs.twitterapi.io/llms.txt
> Use this file to discover all available pages before exploring further.

# Log in

> Log in to an X account with email, username, password and 2FA secret to get login cookies for the v2 posting endpoints. 10,000 credits per login.

Log in directly using your email, username, password, and 2FA secret key. And obtain the login\_cookies,  to post tweets, etc. Please note that the login\_cookies obtained through login\_v2 can only be used for APIs with the "v2" suffix, such as create\_tweet\_v2. Price: 10,000 credits (\$0.10 per call). We highly recommend enabling 2FA for your login – otherwise, the login\_cookies you obtain may be faulty, preventing you from posting tweets.


## OpenAPI

````yaml POST /twitter/user_login_v2
openapi: 3.0.1
info:
  title: TwitterAPI.io API
  description: >-
    Real-time access to public X (Twitter) data: tweets, users, search, lists,
    communities and streams. Pay per item returned.
  license:
    name: MIT
  version: 1.0.0
servers:
  - url: https://api.twitterapi.io
security:
  - ApiKeyAuth: []
paths:
  /twitter/user_login_v2:
    post:
      description: >-
        Log in directly using your email, username, password, and 2FA secret
        key. And obtain the login_cookies,  to post tweets, etc. Please note
        that the login_cookies obtained through login_v2 can only be used for
        APIs with the "v2" suffix, such as create_tweet_v2. Price: 10,000
        credits ($0.10 per call). We highly recommend enabling 2FA for your
        login – otherwise, the login_cookies you obtain may be faulty,
        preventing you from posting tweets.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - user_name
                - email
                - password
                - proxy
              properties:
                user_name:
                  type: string
                  description: User name.Must be set
                email:
                  type: string
                  description: Email.Must be set
                password:
                  type: string
                  description: The password of the user
                totp_secret:
                  type: string
                  description: >-
                    TOTP/2FA secret (base32 seed, not a 6-digit code). Optional,
                    but strongly recommended — accounts without 2FA may yield a
                    login_cookie that gets flagged and can't post. To obtain: on
                    X, enable 2FA, choose "can't scan the QR code", and X shows
                    a 10+ character string — that's the TOTP secret.
                proxy:
                  type: string
                  description: >-
                    The proxy to use.Please use high-quality residential proxies
                    and avoid free proxies.Required.Example:
                    http://username:password@ip:port . You can get proxy from:
                    https://www.webshare.io/?referral_code=4e0q1n00a504
      responses:
        '200':
          description: Login response
          content:
            application/json:
              schema:
                type: object
                properties:
                  login_cookies:
                    type: string
                    description: >-
                      The login cookie of the user.Use this cookie to post
                      tweets, etc.You can only call v2 APIs with this cookie.If
                      your account is in good standing and you're using
                      residential proxies, the cookies will generally remain
                      valid indefinitely.
                  status:
                    type: string
                    description: Status of the request.success or error
                  message:
                    type: string
                    description: Message of the request.error message
        '400':
          description: Unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    Error:
      required:
        - error
        - message
      type: object
      properties:
        error:
          type: integer
          format: int32
        message:
          type: string
  securitySchemes:
    ApiKeyAuth:
      type: apiKey
      in: header
      name: X-API-Key

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.