/*
 * Copyright (c) 2025 SAP SE or an SAP affiliate company. All rights reserved.
 */
package de.hybris.platform.orgprescriptiondecoderservice;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpRequest;
import org.springframework.http.client.ClientHttpRequestExecution;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.util.StreamUtils;


public class LoggingRequestInterceptor implements ClientHttpRequestInterceptor
{

	private static final Logger LOG = LoggerFactory.getLogger(LoggingRequestInterceptor.class);

	@Override
	public ClientHttpResponse intercept(final HttpRequest request, final byte[] body, final ClientHttpRequestExecution execution)
			throws IOException
	{
		// Log the request
		logRequest(request, body);

		// Execute the request
		final ClientHttpResponse response = execution.execute(request, body);

		// Log the response
		logResponse(response);

		return response;
	}

	private void logRequest(final HttpRequest request, final byte[] body) throws IOException
	{
		if (LOG.isDebugEnabled())
		{
			LOG.debug("===========================request begin================================================");
			LOG.debug("URI         : {}", request.getURI());
			LOG.debug("Method      : {}", request.getMethod());
			LOG.debug("Headers     : {}", request.getHeaders());
			LOG.debug("Request body: {}", new String(body, StandardCharsets.UTF_8));
			LOG.debug("==========================request end=================================================");
		}
	}

	private void logResponse(final ClientHttpResponse response) throws IOException
	{
		if (LOG.isDebugEnabled())
		{
			LOG.debug("===========================response begin================================================");
			LOG.debug("Status code  : {}", response.getStatusCode());
			LOG.debug("Status text  : {}", response.getStatusText());
			LOG.debug("Headers      : {}", response.getHeaders());
			// Consume the response body to log it. Be careful, as consuming the stream here
			// means the actual consuming application might need to re-read it if not cached.
			// For simple logging, this is generally fine.
			LOG.debug("Response body: {}", StreamUtils.copyToString(response.getBody(), StandardCharsets.UTF_8));
			LOG.debug("===========================response end=================================================");
		}
	}
}