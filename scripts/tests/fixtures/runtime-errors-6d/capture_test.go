package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/aisa-one/aisa-services/packages/apikey"
	"github.com/aisa-one/aisa-services/packages/integrationmetering/accounting"
	"github.com/gin-gonic/gin"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

func TestAC19ExportActualPresenters(t *testing.T) {
	gin.SetMode(gin.TestMode)
	type row struct {
		Class           string `json:"class"`
		Variant         string `json:"variant"`
		Status          int    `json:"status"`
		Body            any    `json:"body"`
		RequestIDHeader string `json:"request_id_header,omitempty"`
	}
	var rows []row
	cases := []struct {
		class, variant string
		write          func(*gin.Context)
	}{
		{"authentication", "api_key", func(c *gin.Context) { writeAPIKeyAuthenticationError(c, apikey.ErrAPIKeyNotFound) }},
		{"parameters", "native_request", func(c *gin.Context) {
			writeIntegrationJSON(c, http.StatusBadRequest, gin.H{"error": "request does not match the endpoint contract"})
		}},
		{"budget", "estimate_cap", func(c *gin.Context) { writeMeteredV2ReserveError(c, accounting.ErrMaxPriceExceeded) }},
		{"idempotency", "generic", func(c *gin.Context) { writeMeteredV2ReserveError(c, accounting.ErrRequestAlreadyComplete) }},
		{"idempotency", "similarweb_compatibility", func(c *gin.Context) {
			writeMeteredV2ReserveErrorForSurface(c, accounting.ErrRequestAlreadyComplete, true)
		}},
		{"upstream", "native_transport", func(c *gin.Context) {
			writeIntegrationJSON(c, http.StatusBadGateway, gin.H{"error": "provider request failed"})
		}},
		{"upstream", "managed_transport", func(c *gin.Context) {
			writeSimilarwebProductError(c, http.StatusServiceUnavailable, "provider_unavailable", "Similarweb is temporarily unavailable.", nil)
		}},
		{"configuration_dependency", "timeout", func(c *gin.Context) { writeMeteredV2ReserveError(c, context.DeadlineExceeded) }},
		{"configuration_dependency", "invalid_config", func(c *gin.Context) { writeMeteredV2ReserveError(c, errors.New("invalid fixture configuration")) }},
	}
	for _, tc := range cases {
		w := httptest.NewRecorder()
		c, _ := gin.CreateTestContext(w)
		c.Request = httptest.NewRequest(http.MethodGet, "/apis/v1/example", nil)
		c.Request.Header.Set("X-Request-ID", "example-request-id")
		tc.write(c)
		var body any
		if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
			t.Fatal(err)
		}
		rows = append(rows, row{tc.class, tc.variant, w.Code, body, w.Header().Get("X-Request-ID")})
	}
	raw, err := json.MarshalIndent(map[string]any{"scope": "direct actual presenters with controlled errors; not routing/provider/production calls", "cases": rows}, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(os.Getenv("AC19_PRESENTER_OUTPUT"), append(raw, '\n'), 0600); err != nil {
		t.Fatal(err)
	}
}
