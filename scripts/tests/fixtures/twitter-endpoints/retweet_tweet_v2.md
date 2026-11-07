> ## Documentation Index
> Fetch the complete documentation index at: https://docs.twitterapi.io/llms.txt
> Use this file to discover all available pages before exploring further.

# Retweet Tweet 

> Retweet a tweet.You must set the login_cookies.You can get the login_cookies from /twitter/user_login_v2.Price: 60 credits ($0.0006 per call). Returns success if the tweet is already retweeted. If X rejects the retweet, status is "error" with X's reason.



## OpenAPI

````yaml POST /twitter/retweet_tweet_v2
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
  /twitter/retweet_tweet_v2:
    post:
      description: >-
        Retweet a tweet.You must set the login_cookies.You can get the
        login_cookies from /twitter/user_login_v2.Price: 60 credits ($0.0006 per
        call). Returns success if the tweet is already retweeted. If X rejects
        the retweet, status is "error" with X's reason.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - login_cookies
                - tweet_id
                - proxy
              properties:
                login_cookies:
                  type: string
                  description: >-
                    The login cookies of the user.You can get the login_cookie
                    from /twitter/user_login_v2.Must be set
                tweet_id:
                  type: string
                  description: The id of the tweet to retweet.Must be set
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