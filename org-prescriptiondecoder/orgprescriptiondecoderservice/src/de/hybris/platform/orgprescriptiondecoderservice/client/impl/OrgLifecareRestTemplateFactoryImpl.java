/*
 * Copyright (c) 2025 SAP SE or an SAP affiliate company. All rights reserved.
 */
package de.hybris.platform.orgprescriptiondecoderservice.client.impl;

import de.hybris.platform.orgprescriptiondecoderservice.client.OrgLifecareRestTemplateFactory;

import java.util.List;

import org.springframework.http.client.ClientHttpRequestFactory;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.web.client.RestOperations;
import org.springframework.web.client.RestTemplate;


/**
 *
 */
public class OrgLifecareRestTemplateFactoryImpl implements OrgLifecareRestTemplateFactory
{
	private List<ClientHttpRequestInterceptor> httpRequestInterceptors;
	private ClientHttpRequestFactory clientHttpRequestFactory;
	private List<HttpMessageConverter<?>> messageConverters;

	@Override
	public RestOperations createTemplate()
	{
		final RestTemplate restTemp = new RestTemplate(getClientHttpRequestFactory());
		restTemp.setInterceptors(getHttpRequestInterceptors());
		restTemp.setMessageConverters(getMessageConverters());
		return restTemp;
	}

	protected List<HttpMessageConverter<?>> getMessageConverters()
	{
		return messageConverters;
	}

	public void setMessageConverters(final List<HttpMessageConverter<?>> messageConverters)
	{
		this.messageConverters = messageConverters;
	}

	protected List<ClientHttpRequestInterceptor> getHttpRequestInterceptors()
	{
		return httpRequestInterceptors;
	}

	public void setHttpRequestInterceptors(final List<ClientHttpRequestInterceptor> httpRequestInterceptors)
	{
		this.httpRequestInterceptors = httpRequestInterceptors;
	}

	protected ClientHttpRequestFactory getClientHttpRequestFactory()
	{
		return clientHttpRequestFactory;
	}

	public void setClientHttpRequestFactory(final ClientHttpRequestFactory clientHttpRequestFactory)
	{
		this.clientHttpRequestFactory = clientHttpRequestFactory;
	}

}
