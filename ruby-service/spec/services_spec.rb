# frozen_string_literal: true

require_relative 'spec_helper'
require_relative '../app/services/authentication_service'
require_relative '../app/services/cache_manager'
require_relative '../app/services/user_session_manager'

RSpec.describe UserSessionManager do
  before do
    described_class.class_variable_get(:@@active_sessions).clear
    described_class.class_variable_get(:@@session_data).clear
  end

  after do
    described_class.class_variable_get(:@@active_sessions).clear
    described_class.class_variable_get(:@@session_data).clear
  end

  it 'cleans expired sessions without mutating the session hash while iterating' do
    manager = described_class.new
    token = manager.create_session(123)
    manager.store_session_data(token, 'payload')

    sessions = described_class.class_variable_get(:@@active_sessions)
    sessions[token][:created_at] = Time.now - 3601

    expect { manager.cleanup_expired_sessions }.not_to raise_error
    expect(manager.get_all_active_sessions).to be_empty
    expect(manager.get_session_data(token)).to be_empty
  end
end

RSpec.describe AuthenticationService do
  let(:session_manager) { instance_double(UserSessionManager) }
  let(:db_handler) { instance_double('DatabaseQueryHandler', find_user_by_username: user) }
  let(:user) do
    {
      'id' => 1,
      'password_hash' => Digest::SHA256.hexdigest('correct-password'),
      'role' => 'user'
    }
  end

  it 'blocks on the fifth failed attempt in the active rate-limit window' do
    service = described_class.new(session_manager, db_handler)

    expect(service).to receive(:block_user).with('alice').once

    5.times do
      service.authenticate('alice', 'wrong-password')
    end
  end

  it 'prunes old failed attempts before applying the rate-limit threshold' do
    current_time = Time.now
    service = described_class.new(session_manager, db_handler)
    service.instance_variable_set(:@failed_attempts, { 'alice' => [current_time - 301, current_time - 600] })

    allow(Time).to receive(:now).and_return(current_time)
    expect(service).not_to receive(:block_user)

    service.authenticate('alice', 'wrong-password')

    expect(service.instance_variable_get(:@failed_attempts)['alice']).to eq([current_time])
  end
end

RSpec.describe CacheManager do
  it 'keeps cache access history bounded' do
    cache = described_class.new(10, 3)

    cache.set('first', 1)
    cache.get('first')
    cache.get('missing')
    cache.set('second', 2)

    expect(cache.stats[:history_size]).to eq(3)
  end
end
