/*
 * Copyright (c) 2025 SAP SE or an SAP affiliate company. All rights reserved.
 */
package de.hybris.platform.orgprescriptiondecoderservice.client;

import org.springframework.web.client.RestOperations;


/**
 *
 */
public interface OrgLifecareRestTemplateFactory
{
	/**
	 * Create Rest Template
	 *
	 * @return Return {@link RestOperations}
	 */
	RestOperations createTemplate();
}