/*
 * Copyright (c) 2021 SAP SE or an SAP affiliate company. All rights reserved.
 */
package de.hybris.platform.orgprescriptiondecoderservice.service;

public interface OrgprescriptiondecoderserviceService
{
	String getHybrisLogoUrl(String logoCode);

	void createLogo(String logoCode);
}
